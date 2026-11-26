"""LLM-written context for each chunk: a summary of its chapter, or of the passages around it."""
from typing import List

from langchain_core.documents import Document
from langchain_openrouter import ChatOpenRouter
from openrouter.errors import TooManyRequestsResponseError

from .index_version import INDEX_VERSION
from .store import summaries_vector_store, populate_vector_db
from podcast_generation.agents.content_specialists.utils import get_book_path
import json, time

MAX_CONCURRENCY = 8

# These summaries are embedded in their own collection and retrieved by semantic search, and they are also
# shown to the QA agent as the "Context" of a chunk. So each one must be self-contained, faithful and
# written in the vocabulary a reader would use when asking about the material.
CHAPTER_SUMMARY_SYSTEM = """You write retrieval summaries for a non-fiction book. You are given the text of one \
chapter. Summarise what that chapter says, so that a reader who has not seen it knows what the book covers there.

Rules:
- Use only the chapter text given. Never add outside knowledge, background, opinions or conclusions of your own. If \
the text is cut off mid-sentence or mid-idea, summarise only what is actually there.
- Cover the chapter as a whole, in the order the author presents it: what question or claim it opens with, the \
argument, evidence or story it develops, and where it leaves the reader.
- Be specific. Keep the author's own terms, names of people, companies, studies and frameworks, numbers, and the \
key examples or stories, because readers will search for exactly these. Prefer "the author argues that X because Y" \
to vague phrases like "discusses the importance of X".
- Make it self-contained. Do not write "this chapter", "the passage", "the text" or "the following". Name the topic \
and the book's subject explicitly instead.
- Ignore page headers and footers, figure captions, tables of contents, indexes, citations lists and other noise. \
If the text is only front or back matter (copyright, acknowledgments, index, ads), reply with one short \
sentence saying so.
- No bullet points, no headings, no \
markdown, no preamble, and no closing remark. Output only the summary."""

GRANULAR_SUMMARY_SYSTEM = """You write retrieval summaries for a non-fiction book. You are given the passages that \
come immediately before and after one position in the book. Summarise what those passages say, so that a reader who \
has not seen them knows what the book discusses around that point.

Rules:
- Use only the passages given. Never add outside knowledge, background, opinions or conclusions of your own. If a \
passage is cut off mid-sentence or mid-idea, summarise only what is actually there.
- Be specific. Keep the author's own terms, names of people, companies, studies and frameworks, numbers, and the \
key examples or stories, because readers will search for exactly these. Prefer "the author argues that X because Y" \
to vague phrases like "discusses the importance of X".
- Say what happens in order: what comes just before this position and what follows it, so the reader can see how \
the argument moves. Label them "Before:" and "After:" when both exist; if only one side exists (start or end of \
the book), give just that side.
- Make it self-contained. Do not write "this section", "the passage", "the text" or "the following". Name the topic \
and the book's subject explicitly instead.
- Ignore page headers and footers, figure captions, tables of contents, indexes, citations lists and other noise. \
If the passages are only front or back matter (copyright, acknowledgments, index, ads), reply with one short \
sentence saying so.
- No bullet points, no headings other than the Before:/After: labels, no \
markdown, no preamble, and no closing remark. Output only the summary."""


def _header(book_title: str, author: str, chapter: str) -> str:
    return f"Book: {book_title}" + (f" by {author}" if author else "") + (f"\nChapter: {chapter}" if chapter else "")


def _summary_prompt(book_title: str, author: str, chapter: str, chapter_content: str) -> str:
    return (
        f"{_header(book_title, author, chapter)}\n\n"
        f"<chapter_content>\n{chapter_content}\n</chapter_content>\n\n"
    )


def _granular_prompt(book_title: str, author: str, chunks: List[Document], idx: int) -> str:
    last = len(chunks) - 1
    prev_prev = chunks[idx - 2].page_content if idx - 1 > 0 else ""
    prev = chunks[idx - 1].page_content if idx > 0 else ""
    nxt = chunks[idx + 1].page_content if idx < last else ""
    nxt_nxt = chunks[idx + 2].page_content if idx + 1 < last else ""
    chapter = chunks[idx].metadata.get("chapter", "")
    return (
        f"{_header(book_title, author, chapter or '')}\n\n"
        f"<before>\n{(f'{prev_prev}\n{prev}').strip() or '(start of the book)'}\n</before>\n\n"
        f"<after>\n{(f'{nxt}\n{nxt_nxt}').strip() or '(end of the book)'}\n</after>"
    )


async def create_chunk_surrounding_summaries(chunks: List[Document], granular: bool = False) -> List[Document]:
    """Write a context summary for every chunk.

    `granular` summarises the two passages on either side of each chunk (one prompt per chunk); otherwise the
    whole chapter a chunk belongs to is summarised once and shared by every chunk in it (one prompt per chapter).
    """
    book_title = chunks[0].metadata.get("Title", "")
    author = chunks[0].metadata.get("Author", "")

    model = ChatOpenRouter(model="z-ai/glm-5.3-flash", temperature=0.3, max_tokens=8192, max_retries=2)

    # Each prompt produces one summary; a group is every chunk that summary is written to.
    groups: dict = {}
    prompts: list = []
    if granular:
        for chunk_idx, chunk in enumerate(chunks):
            groups[chunk_idx] = [(chunk_idx, chunk)]
            prompts.append([("system", GRANULAR_SUMMARY_SYSTEM), ("user", _granular_prompt(book_title, author, chunks, chunk_idx))])
    else:
        for chunk_idx, chunk in enumerate(chunks):
            groups.setdefault(chunk.metadata.get("chapter") or "", []).append((chunk_idx, chunk))
        for ch, members in groups.items():
            prompts.append([("system", CHAPTER_SUMMARY_SYSTEM), ("user", _summary_prompt(
                book_title, author, ch,
                "\n\n".join(chunk.page_content for _, chunk in members),
            ))])

    results = await model.abatch(prompts, config={"max_concurrency": MAX_CONCURRENCY}, return_exceptions=True)

    summary_docs: list[Document] = []
    for prompt_idx, (key, summary) in enumerate(zip(groups, results)):
        if isinstance(summary, BaseException):
            for attempt in range(3):
                try:
                    summary = await model.ainvoke(prompts[prompt_idx])
                except TooManyRequestsResponseError as err:
                    if attempt == 2:
                        summary = None
                        break
                    else:
                        retry_after = err.raw_response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after else 2 ** (attempt + 1)
                        print(f"Rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{3})")
                        time.sleep(delay)
            if summary is None:
                print(f"[Error occured during context generation] - {key!r} skipped.")
                continue
        response = summary.content if isinstance(summary.content, str) else json.dumps(summary.content)
        for chunk_idx, chunk in groups[key]:
            chunk.metadata['context_summary'] = summary.content
            chunk.metadata['id'] = chunk_idx
            summary_meta = {"id": chunk_idx, "Title": book_title, "book_slug": get_book_path(book_title), "Author": author, "chapter": chunk.metadata.get("chapter"), "index_version": INDEX_VERSION}
            if "start_seconds" in chunk.metadata:  # a video: the summary can be cited at the same moment
                summary_meta["start_seconds"] = chunk.metadata["start_seconds"]
            summary_docs.append(Document(page_content=response, metadata=summary_meta))
    populate_vector_db(summary_docs, summaries_vector_store)
    return chunks