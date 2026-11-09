"""LLM-written context for each chunk (summary of the neighbouring sections)."""
from typing import List

from langchain_core.documents import Document
from langchain_openrouter import ChatOpenRouter
from tqdm import tqdm


BATCH_SIZE = 5


async def create_chunk_surrounding_summaries(chunks: List[Document]) -> List[Document]:
    model = ChatOpenRouter(model="inclusionai/ling-3.1-flash", temperature=0.1, max_tokens=1024)
    prompts: list = []
    indices: list[int] = [] 
    last = len(chunks) - 1
    for idx in tqdm(range(len(chunks))):
        prev = chunks[idx - 1].page_content if idx > 0 else ""
        nxt = chunks[idx + 1].page_content if idx < last else ""
        prompt = f"Summarise these sections from a book that surrounds the current chunk, so the agent will have enough information in which context it is located. Return only the summary! \n\n Previous section: {prev}\n Following section: {nxt}"
        prompts.append([("user", prompt)])
        indices.append(idx)
        # Flush a full batch, and whatever is left after the final chunk.
        if len(prompts) == BATCH_SIZE or idx == last:
            summaries = await model.abatch(prompts)
            for chunk_idx, summary in zip(indices, summaries):
                chunks[chunk_idx].metadata['context_summary'] = summary.content
            prompts, indices = [], []
    return chunks
