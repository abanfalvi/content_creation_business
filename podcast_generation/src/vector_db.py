# Preprocess the content from the books and load them into a vector DB
# Strategy: specify chunk location in metadata, extract summary from chunk, add citation
    #  HDBSCAN clustering groups similar chunks together; cluster centroids become "parent nodes" (e.g., a cluster might represent a theme like "AI Bias")
    # A fine-tuned T5 model identifies predicate-argument relationships between chunks (e.g., "Overfishing reduces fish populations")
    # This creates a semantic graph that powers features like mind maps and thematic navigation

import requests
from openrouter import OpenRouter
import os
import zipfile
import io
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

load_dotenv()

EMBEDDING_MODEL = "perplexity/pplx-embed-v1-0.6b"

class OpenRouterEmbedding(Embeddings):
    """LangChain Embeddings adapter around OpenRouter's embeddings endpoint."""

    def __init__(self, model: str = EMBEDDING_MODEL, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with OpenRouter(api_key=self.api_key) as open_router:
            res = open_router.embeddings.generate(input=texts, model=self.model)

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
def parse_pdf(filepath):
    token = os.getenv("MINERU_API_KEY", "")
    url = "https://mineru.net/api/v4/file-urls/batch"
    header = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "files": [{"name": filepath, "data_id": "Contagious_book", "page_ranges": "8-169", "is_ocr": True,}],
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

def save_markdown(zip_url: str, output_path: str):
    res = requests.get(zip_url)
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        md_name = next(n for n in zf.namelist() if n.endswith(".md"))
        with zf.open(md_name) as f, open(output_path, "wb") as out:
            out.write(f.read())


def chunk_document(md_path):
    with open(md_path, "r") as f:
        content = f.read()
    headers_to_split_on = [
        ("##", "Header 2"),
    ]
    separators = [
        "##/s+/d+"
    ]
    # recursive_splitter = RecursiveCharacterTextSplitter(separators, is_separator_regex=True, chunk_size=2048)
    # splits = recursive_splitter.split_text(content)

    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on)
    md_header_splits = markdown_splitter.split_text(content)
    vector_store.add_documents(md_header_splits)
    return None
