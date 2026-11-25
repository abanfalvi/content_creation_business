from datalab_sdk import DatalabClient, ConvertOptions
from dotenv import load_dotenv
from pathlib import Path
import json, os
from tqdm import tqdm

load_dotenv()

if __name__ == "__main__":
    from podcast_generation.agents.content_specialists.utils import get_book_path
    from podcast_generation.book_preprocessing.source_meta import book_file

    book_paths = [
        "D:/Downloads/The Generative AI Career Masterplan (Ali Arsanjani, Sadid Hasan, Maxime Labonne etc.).pdf"
    ]
    book_names = [
         "the_generative_ai_career_masterplan"
    ]
    for p, n in tqdm(zip(book_paths, book_names)):
        md_path = book_file(n)
        result = DatalabClient().convert(
            p, options=ConvertOptions(mode="fast", output_format="markdown", paginate=True, extras="extract_bookmarks", disable_image_extraction=True),
        )
        if not result.success:
            raise RuntimeError(result.error or "Conversion failed")
        
        meta = result.metadata or {}
        toc: list = meta.get("pdf_bookmarks", [])

        with open(md_path, "w", encoding="utf-8") as f:
                f.write(result.markdown)
        if result.metadata:
            Path(md_path).with_suffix(".metadata.json").write_text(
                json.dumps(toc, indent=2), encoding="utf-8"
            )
