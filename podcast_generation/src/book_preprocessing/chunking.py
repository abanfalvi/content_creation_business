"""Split a book's Markdown into chunks and tag them with chapter + context metadata."""
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tqdm import tqdm

from src.agents.content_specialists.utils import get_book_path

from .context import create_chunk_surrounding_summaries
from .toc import extract_toc_titles, match_toc_to_headers


async def chunk_document(md_path: str, book_title: str, author: str):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    toc_titles = extract_toc_titles(content)
    boundaries = match_toc_to_headers(content, toc_titles)

    # Title is for display; book_slug is the key retrieval filters on (same slug as data/<slug>/).
    book_doc = Document(
        page_content=content,
        metadata={"Title": book_title, "book_slug": get_book_path(book_title), "Author": author},
    )
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
