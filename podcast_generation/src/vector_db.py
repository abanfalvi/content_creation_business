# Preprocess the content from the books and load them into a vector DB
# Strategy: specify chunk location in metadata, extract summary from chunk, add citation
    # HDBSCAN clustering groups similar chunks together; cluster centroids become "parent nodes" (e.g., a cluster might represent a theme like "AI Bias")
    # A fine-tuned T5 model identifies predicate-argument relationships between chunks (e.g., "Overfishing reduces fish populations")
    # This creates a semantic graph that powers features like mind maps and thematic navigation

# TODO: apply HDBSCAN clustering
# TODO: identify predicate-argument relationships between chunks

import requests
from openrouter import OpenRouter
from openrouter.errors import TooManyRequestsResponseError
import os
import time, json, math
import zipfile
import io
import difflib
import re
from dotenv import load_dotenv
from typing import List
from tqdm import tqdm
import numpy as np
import umap
import hdbscan

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openrouter import ChatOpenRouter

from .agents.content_specialists.utils import get_book_path

load_dotenv()

EMBEDDING_MODEL = "sentence-transformers/all-minilm-l6-v2"

class OpenRouterEmbedding(Embeddings):
    """LangChain Embeddings adapter around OpenRouter's embeddings endpoint."""

    def __init__(self, model: str = EMBEDDING_MODEL, api_key: str | None = None, max_retries: int = 5):
        self.model = model
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.max_retries = max_retries

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        for attempt in range(self.max_retries):
            try:
                with OpenRouter(api_key=self.api_key) as open_router:
                    res = open_router.embeddings.generate(input=texts, model=self.model)
                break
            except TooManyRequestsResponseError as err:
                if attempt == self.max_retries - 1:
                    raise
                retry_after = err.raw_response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                print(f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(delay)

        # `index` maps each embedding back to its position in `texts`,
        # since the API doesn't guarantee `data` preserves input order.
        ordered = sorted(res.data, key=lambda d: d.index)
        return [d.embedding for d in ordered]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

embeddings = OpenRouterEmbedding()
vector_store = Chroma(
    collection_name="books_for_podcast",
    embedding_function=embeddings,
    persist_directory="./podcast_books_db",  # Where to save data locally, remove if not necessary
)

# It currently produces a url for zip file
def parse_pdf(filepath, book_name, page_ranges):
    token = os.getenv("MINERU_API_KEY", "")
    url = "https://mineru.net/api/v4/file-urls/batch"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [{"name": filepath, "data_id": book_name, "page_ranges": page_ranges, "is_ocr": True,}],
        "model_version": "vlm",
        "language": "en"
    }
    file_path = [filepath]

    try:
        response = requests.post(url,headers=header,json=data)
        if response.status_code == 200:
            result = response.json()
            print('response success. result:{}'.format(result))
            if result["code"] == 0:
                batch_id = result["data"]["batch_id"]
                urls = result["data"]["file_urls"]
                print('batch_id:{},urls:{}'.format(batch_id, urls))
                for i in range(0, len(urls)):
                    with open(file_path[i], 'rb') as f:
                        requests.put(urls[i], data=f)
                    poll_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
                    while True:
                        result = requests.get(poll_url, headers=header).json()
                        file_result = result["data"]["extract_result"][0]
                        if file_result["state"] == "done":
                            return file_result["full_zip_url"]
                        if file_result["state"] == "failed":
                            raise RuntimeError(file_result.get("err_msg"))
                        # time.sleep(3)
            else:
                print('apply upload url failed,reason:{}'.format(result["msg"]))
        else:
            print('response not success. status:{} ,result:{}'.format(response.status_code, response))
    except Exception as err:
        print(err)

def save_markdown(zip_url: str, output_path: str, append: bool = False):
    res = requests.get(zip_url)
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        md_name = next(n for n in zf.namelist() if n.endswith(".md"))
        mode = "ab" if append and os.path.exists(output_path) else "wb"
        with zf.open(md_name) as f, open(output_path, mode) as out:
            out.write(f.read())

async def create_chunk_surrounding_summaries(chunks: List[Document]) -> List[Document]:
    from tqdm import tqdm
    for idx, chunk in tqdm(enumerate(chunks)):
        prev = chunks[idx-1] if idx != 0 else ""
        next = chunks[idx+1] if idx != len(chunks) - 1 else "" 
        model = ChatOpenRouter(model="upstage/solar-pro4", temperature=0.1, max_tokens=1024)
        prompt = f"Summarise these sections from a book that surrounds the current chunk, so the agent will have enough information in which context it is located. Return only the summary! \n\n Previous section: {prev}\n Following section: {next}"
        summary = await model.ainvoke([("user", prompt)])
        chunks[idx].metadata['context_summary'] = summary.content
    return chunks

def extract_toc_titles(content: str) -> list[str]:
    # TOC block = everything between the "Table of Contents" header and the next header
    toc_match = re.search(
        r"^#{1,6}\s*Table of Contents\s*\n(.*?)(?=^#{1,6}\s)",
        content, re.MULTILINE | re.DOTALL,
    )
    if not toc_match:
        return []
    toc_block = toc_match.group(1)
    # Each entry is a non-empty line
    return [line.strip() for line in toc_block.splitlines() if line.strip()]

def match_toc_to_headers(content: str, toc_titles: list[str]) -> list[tuple[str, int]]:
    headers = [
        (m.start(), m.group(1).strip())
        for m in re.finditer(r"^#{1,6}\s*(.+)$", content, re.MULTILINE)
    ]
    boundaries = []
    header_idx = 0
    for title in toc_titles:
        norm_title = title.strip().lower()
        while header_idx < len(headers):
            offset, header_text = headers[header_idx]
            header_idx += 1
            if header_text.strip().lower() == norm_title:
                boundaries.append((title, offset))
                break
            elif difflib.SequenceMatcher(None, header_text.lower(), norm_title).ratio() > 0.9:
                boundaries.append((title, offset))
                break
    return boundaries   

async def chunk_document(md_path: str, book_title: str, author: str):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    toc_titles = extract_toc_titles(content)
    boundaries = match_toc_to_headers(content, toc_titles)

    book_doc = Document(page_content=content, metadata={"Title": book_title, "Author": author})
    separators = [
        r"\n#{1,6}\s",  # markdown headers
        "\n\n\n",       # chapter/section breaks
        "\n\n",         # paragraph breaks
        "\n",           # line breaks
        ". ",           # sentence end
        "! ",
        "? ",
        "; ",
        ", ",
        " ",            # word boundary
        "",             # character fallback
    ]
    
    recursive_splitter = RecursiveCharacterTextSplitter(separators, is_separator_regex=True, chunk_size=2048, add_start_index=True)
    splits = recursive_splitter.split_documents([book_doc])
    print("Total number of splits created: ", len(splits))
    chunks = await create_chunk_surrounding_summaries(splits)

    for idx, boundary in enumerate(boundaries):
        for chunk in tqdm(chunks):
            # print("Main chapter boundary: ", boundary[1])
            # print("Chunk start indices: ", chunk.metadata['start_index'])
            if boundary[1] <= chunk.metadata['start_index']:
                chunk.metadata['chapter'] = boundary[0]
            else:
                # chunk.metadata['chapter'] = "Preamble"
                continue

    # vector_store.add_documents(splits)
    return chunks

def populate_vector_db(
    chunks: List[Document],
    vector_store: Chroma = vector_store,
    batch_size: int = 6,
    pause_seconds: float = 10,
) -> None:
    for idx in tqdm(range(0, len(chunks), batch_size)):
        batch = chunks[idx: idx + batch_size]
        vector_store.add_documents(batch)
        if idx + batch_size < len(chunks):
            time.sleep(pause_seconds)

async def preprocessing_pipeline(book_genre: str, book_name: str, end_page: int) -> str:
    with open("src/book_list.json", "r") as f:
        data = json.dumps(f.read())
    path_found = False
    for genre, books in data["list_of_books"]["wishlist"]:
        if genre == book_genre:
            for book in books:
                if book["title"] == book_name:
                    book_title = book['title']
                    book_author = book['author']
                    filepath = book['filepath']
                    if filepath:
                        path_found = True
                        break
                    else:
                        return "Filepath has not been provided in src/book_list.json"
        if path_found:
            break
    book_name = get_book_path(book_name)
    if end_page < 200:
        page_ranges = f"1-{str(end_page)}"
        save_markdown(zip_url=parse_pdf(filepath, book_name, page_ranges), output_path=f"data/{book_name}/{book_name}_content.md")
    else:
        n = math.ceil(end_page / 200)
        for run in range(n):
            if run == 0:
                page_ranges = f"1-200"
                save_markdown(zip_url=parse_pdf(filepath, book_name, page_ranges), output_path=f"data/{book_name}/{book_name}_content.md")
            else:
                start_page = str(200*run + 1)
                last_page = str(min(200*(run+1), end_page))
                page_ranges = f"{start_page}-{last_page}"
                save_markdown(zip_url=parse_pdf(filepath, book_name, page_ranges), output_path=f"data/{book_name}/{book_name}_content.md", append=True)

    book_chunks = await chunk_document(md_path=f"data/{book_name}/{book_name}_book_content.md", book_title=book_title, author=book_author)
    populate_vector_db(book_chunks)
    return f"{book_name} as been preprocessed successfully!"

def apply_hdbscan_clustering(embeddings: List[List[float]]):
    X = np.array(embeddings)

    reducer = umap.UMAP(n_neighbors=15, n_components=10, metric="cosine", random_state=42)
    X_reduced = reducer.fit_transform(X)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=5,      # smallest group size worth calling a "theme"
        min_samples=None,        # defaults to min_cluster_size; raise it to be more conservative about noise
        metric="euclidean",      # UMAP output is Euclidean regardless of input metric
        cluster_selection_method="eom",  # "excess of mass" — favors stable, well-separated clusters over "leaf"
    )
    labels = clusterer.fit_predict(X_reduced)  # array of cluster ids; -1 means "noise, no theme"

    centroids = {}
    for label in set(labels) - {-1}:
        member_vectors = X[labels == label]
        centroids[label] = member_vectors.mean(axis=0)

    # Label centroids with a theme
    # Add the theme/cluster id to the metadata of the chunks
    # Add clusters to a new collection
    themes_store = Chroma(collection_name="book_themes", embedding_function=embeddings, persist_directory="./podcast_books_db")

    for cluster_id, centroid in centroids.items():
        theme_doc = Document(
            page_content=theme_label,          # LLM-generated name, e.g. "AI Bias"
            metadata={
                "cluster_id": cluster_id,
                "book_title": book_title,
                "member_chunk_ids": [...],     # ids of chunks in this cluster
                "size": len(member_vectors),
            },
        )
        themes_store.add_documents([theme_doc], embeddings=[centroid.tolist()])

    # Every time a new book comes in, we can re-cluster 
