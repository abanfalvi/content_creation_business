"""LLM-written context for each chunk (summary of the neighbouring sections)."""
from typing import List

from langchain_core.documents import Document
from langchain_openrouter import ChatOpenRouter
from openrouter.errors import TooManyRequestsResponseError

from .store import summaries_vector_store, populate_vector_db
from podcast_generation.agents.content_specialists.utils import get_book_path
import json, time

MAX_CONCURRENCY = 8

# These summaries are embedded in their own collection and retrieved by semantic search, and they are also
# shown to the QA agent as the "Context" of a chunk. So each one must be self-contained, faithful and
# written in the vocabulary a reader would use when asking about the material.
SUMMARY_SYSTEM = """You write retrieval summaries for a non-fiction book. You are given the passages that come \
immediately before and after one position in the book. Summarise what those passages say, so that a reader who \
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


def _summary_prompt(book_title: str, author: str, chapter: str, before: str, after: str) -> str:
    header = f"Book: {book_title}" + (f" by {author}" if author else "") + (f"\nChapter: {chapter}" if chapter else "")
    return (
        f"{header}\n\n"
        f"<before>\n{before.strip() or '(start of the book)'}\n</before>\n\n"
        f"<after>\n{after.strip() or '(end of the book)'}\n</after>"
    )


async def create_chunk_surrounding_summaries(chunks: List[Document]) -> List[Document]:
    book_title = chunks[0].metadata.get("Title", "")
    author = chunks[0].metadata.get("Author", "")
    chapter = chunks[0].metadata.get("chapter", "")

    model = ChatOpenRouter(model="z-ai/glm-5.3-flash", temperature=0.3, max_tokens=4096, max_retries=2)
    prompts: list = []
    last = len(chunks) - 1
    for idx in range(len(chunks)):
        prev_prev = chunks[idx - 2].page_content if idx - 1 > 0 else ""
        prev = chunks[idx - 1].page_content if idx > 0 else ""
        nxt = chunks[idx + 1].page_content if idx < last else ""
        nxt_nxt = chunks[idx + 2].page_content if idx + 1 < last else ""
        prompt = _summary_prompt(
            book_title, author, chunks[idx].metadata.get("chapter", "") or "",
            before=f"{prev_prev}\n{prev}", after=f"{nxt}\n{nxt_nxt}",
        )
        prompts.append([("system", SUMMARY_SYSTEM), ("user", prompt)])

    results = await model.abatch(prompts, config={"max_concurrency": MAX_CONCURRENCY}, return_exceptions=True)

    summary_docs: list[Document] = []
    sleep_time = [10, 20, 30]
    for chunk_idx, summary in enumerate(results):
        if isinstance(summary, BaseException):
            for attempt in range(3):
                try:
                    summary = await model.ainvoke(prompts[chunk_idx])
                except:
                    if attempt == 2:
                        summary = None
                        break
                    else:
                        time.sleep(sleep_time[attempt])
                        continue
            if summary is None:
                print(f"[Error occured during context generation] - chunk {chunk_idx} skipped. Error:\n {summary!r}")
                continue
        chunks[chunk_idx].metadata['context_summary'] = summary.content
        chunks[chunk_idx].metadata['id'] = chunk_idx
        response = summary.content if isinstance(summary.content, str) else json.dumps(summary.content)
        summary_docs.append(Document(page_content=response, metadata={"id": chunk_idx, "Title": book_title, "book_slug": get_book_path(book_title), "Author": author, "chapter": chapter}))
    populate_vector_db(summary_docs, summaries_vector_store)
    return chunks
