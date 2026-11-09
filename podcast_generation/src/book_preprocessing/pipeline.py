"""Preprocess the content from the books and load them into a vector DB.

Strategy: specify chunk location in metadata, extract summary from chunk, add citation
    # HDBSCAN clustering groups similar chunks together; cluster centroids become "parent nodes" (e.g., a cluster might represent a theme like "AI Bias")
    # A fine-tuned T5 model identifies predicate-argument relationships between chunks (e.g., "Overfishing reduces fish populations")
    # This creates a semantic graph that powers features like mind maps and thematic navigation

Pipeline: PDF -> Markdown (pdf_parsing) -> chunks + metadata (chunking, toc, context) -> Chroma (store)
          -> line-cited book digest for the expert builder and planner (digest)
"""
import json
import math
import os

from src.agents.content_specialists.utils import get_book_path

from .chunking import chunk_document
from .digest import generate_book_digest
from .pdf_parsing import parse_pdf, save_markdown
from .store import populate_vector_db


async def preprocessing_pipeline(book_genre: str, book_name: str, end_page: int) -> str:
    with open("src/book_list.json", "r") as f:
        data = json.loads(f.read())
    path_found = False
    for genre, books in data["list_of_books"]["wishlist"].items():
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
    os.makedirs(f"data/{book_name}", exist_ok=True)
    if end_page < 200:
        page_ranges = f"1-{str(end_page)}"
        zip_url = parse_pdf(filepath, book_name, page_ranges)
        assert(zip_url is not None)
        save_markdown(zip_url=zip_url, output_path=f"data/{book_name}/book_content.md")
    else:
        n = math.ceil(end_page / 200)
        for run in range(n):
            if run == 0:
                page_ranges = f"1-200"
                zip_url = parse_pdf(filepath, book_name, page_ranges)
                assert(zip_url is not None)
                save_markdown(zip_url=zip_url, output_path=f"data/{book_name}/book_content.md")
            else:
                start_page = str(200*run + 1)
                last_page = str(min(200*(run+1), end_page))
                page_ranges = f"{start_page}-{last_page}"
                zip_url = parse_pdf(filepath, book_name, page_ranges)
                assert(zip_url is not None)
                save_markdown(zip_url=zip_url, output_path=f"data/{book_name}/book_content.md", append=True)
                
    book_chunks = await chunk_document(md_path=f"data/{book_name}/book_content.md", book_title=book_title, author=book_author)
    populate_vector_db(book_chunks)
    # Regenerated only if the book file changed since the last digest.
    digest_status = await generate_book_digest(f"data/{book_name}/book_content.md", book_title, book_author)
    return f"{book_name} as been preprocessed successfully!\n{digest_status}"
