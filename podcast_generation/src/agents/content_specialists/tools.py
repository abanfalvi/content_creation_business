from langchain_tavily import TavilySearch, TavilyExtract
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from langchain_cohere import CohereRerank
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
from langchain_core.documents import Document
import json, frontmatter, os
from dotenv import load_dotenv
from typing import List, Tuple
from pathlib import Path

from .state import BookSelectionState, ExpertBuilderState, ScriptDrafterState
from ...vector_db import vector_store
from .utils import get_book_path

load_dotenv()

class BookSelectionTools:
    "List of tools for Book Selection Agent"

    @tool
    def web_search(query: str):
        "Perform web search to find your answer"
        tool=TavilySearch(
            max_results=5,
            topic="general",
            include_answer=True,
            # include_raw_content=False,
            # include_images=False,
            # include_image_descriptions=False,
            # search_depth="basic",
            # time_range="day",
            # include_domains=None,
            # exclude_domains=None,
            # include_favicon=False
            # include_usage=False
        )
        result = tool.invoke(query)
        return result

    @tool
    def extract_web_content(urls: List[str], runtime: ToolRuntime[None, BookSelectionState]) -> Command:
        "Extract the content of the webpage"
        tool = TavilyExtract(
            extract_depth="basic",
            include_images=False,
        )
        result = tool.invoke({"urls": urls})

        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=result,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "current_step": "update_booklist",
            }
        ) 

    @tool
    def update_booklist(book_title: str, author: str, abstract: str, genre: str) -> str:
        "Save/Update the wishlist of the booklist file"
        with open("src/book_list.json", "r") as f:
            data = json.load(f)

        if genre in data["list_of_books"]["wishlist"].keys():
            data["list_of_books"]["wishlist"][genre].append({"title": book_title, "author": author, "abstract": abstract, "filepath": ""})
        else:
            data["list_of_books"]["wishlist"][genre] = []
            data["list_of_books"]["wishlist"][genre].append({"title": book_title, "abstract": abstract, "filepath": ""})

        with open("src/book_list.json", "w") as f:
            json.dump(data, f, indent=4)

        return "Book list has been updated!"

    @tool
    def read_booklist(runtime: ToolRuntime[None, BookSelectionState]) -> Command:
        "Find out what is currently stored in the booklist file"
        with open("src/book_list.json", "r") as f:
            data = json.load(f)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=data,
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "current_step": "find_books",
            }
        ) 

    @tool
    def set_book_to_finish(book_title: str) -> str:
        "Change the book to 'Finished' status"
        with open("src/book_list.json", "r") as f:
            data = json.load(f)
        for topic, books in data["list_of_books"]["wishlist"].items():
            for book in books:
                if book["title"] == book_title:
                    data["list_of_books"]["finished"].setdefault(topic, []).append(book)
                    books.remove(book)
                    break

        with open("src/book_list.json", "w") as f:
            json.dump(data, f, indent=4)

        return f"{book_title} has been moved to 'Finished' status!"

class ExpertProfileTools:

    @tool
    def read_persona(runtime: ToolRuntime[None, ExpertBuilderState]) -> Command:
        "Read the expert persona that has been drafted so far"
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        try:
            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                persona_content = f.read()
        except:
            with open(f"data/{title}/expert_persona.md", "w", encoding="utf-8") as f:
                f.write("")

            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                persona_content = f.read()
        return Command(update={
            "messages": [ToolMessage(content=persona_content, tool_call_id=runtime.tool_call_id)],
            "persona_read": True,
        })

    @tool
    def edit_persona(to_replace: str, replace_with: str, runtime: ToolRuntime[None, ExpertBuilderState]) -> str:
        "Edit the expert persona in certain parts"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        path = f"data/{title}/expert_persona.md"
        with open(path, "r", encoding="utf-8") as f:
            persona_content = f.read()
        count = persona_content.count(to_replace)
        if count == 0:
            return f"Error: old_string not found in {path}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {path}. Include more surrounding context so it's unique."
        new_content = persona_content.replace(to_replace, replace_with)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return "Persona updated!"          

    @tool
    def append_persona(content: str, runtime: ToolRuntime[None, ExpertBuilderState]) -> str:
        "Add further information to the end of the document about the expert persona"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)

        with open(f"data/{title}/expert_persona.md", "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} - has been appended to the expert profile persona!"

    @tool
    def retrieve_info(query: str) -> List[Document]:
        "Retrieve information to understand the content of the book"
        retriever = vector_store.as_retriever(k=25)
        compressor = CohereRerank(model="rerank-v4.0-fast", top_n=5) 
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=retriever
        )
        compressed_docs = compression_retriever.invoke(
            query
        )
        return [{"Chunk content": doc.page_content, "Context summary":doc.metadata["context_summary"]} for doc in compressed_docs]

    @tool
    def read_book_content(runtime: ToolRuntime[None, ExpertBuilderState], offset: int = 1, limit: int = 200) -> str:
        "Read the book's full parsed content by line range (1-indexed). Use this to read a passage in its natural paragraph flow when a retrieve_info chunk feels incomplete or cut off mid-argument."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        with open(f"data/{title}/{title}_book_content.md", "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(offset - 1, 0)
        selected = lines[start:start + limit]
        return "".join(f"{i}\t{line}" for i, line in enumerate(selected, start=offset))

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"src/skills/content_skills/expert_builder_agent/{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[dict] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs("src/skills/content_skills/expert_builder_agent", exist_ok=True)
        all_skills = list(Path("src/skills/content_skills/expert_builder_agent").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"

class ScriptDrafterTools:

    @tool
    def read_script(runtime: ToolRuntime[None, ScriptDrafterState]) -> Command:
        "Read the content of the script draft"
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        try:
            with open(f"data/{title}/script.md", "r", encoding="utf-8") as f:
                script_content = f.read()
        except:
            with open(f"data/{title}/script.md", "w", encoding="utf-8") as f:
                f.write("")

            with open(f"data/{title}/script.md", "r", encoding="utf-8") as f:
                script_content = f.read()
        return Command(update={
            "messages": [ToolMessage(content=script_content, tool_call_id=runtime.tool_call_id)],
            "script_read": True,
        })

    @tool
    def edit_script(to_replace: str, replace_with: str, runtime: ToolRuntime[None, ScriptDrafterState]):
        "Edit the podcast script in specific parts"
        if not runtime.state.get("script_read"):
            return "Error: you must call read_script before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        path = f"data/{title}/script.md"
        with open(path, "r", encoding="utf-8") as f:
            script_content = f.read()
        count = script_content.count(to_replace)
        if count == 0:
            return f"Error: old_string not found in {path}. Read the file again and copy the exact text to replace."
        if count > 1:
            return f"Error: old_string matches {count} locations in {path}. Include more surrounding context so it's unique."
        new_content = script_content.replace(to_replace, replace_with)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return "Script is updated!"

    @tool
    def append_script(content: str, runtime: ToolRuntime[None, ScriptDrafterState]):
        "Add further information/extend the script"
        if not runtime.state.get("script_read"):
            return "Error: you must call read_script before editing. Call it now."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)

        with open(f"data/{title}/script.md", "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} - has been appended to the script!"

    @tool
    def read_personas(runtime: ToolRuntime[None, ScriptDrafterState], host: bool = True):
        "Read the personas that were created: Host or Expert. It will only return either personas based on the input parameters"
        if host:
            with open("data/host_persona.md", "r", encoding="utf-8") as f:
                host_persona = f.read()
            return host_persona
        else:
            book_title = runtime.state.get("book_title")
            title = get_book_path(book_title)
            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                expert_persona = f.read()
            return expert_persona

    @tool
    def read_book_content(runtime: ToolRuntime[None, ScriptDrafterState], offset: int = 1, limit: int = 200) -> str:
        "Read the book's full parsed content by line range (1-indexed). Pass a line number that grep_search reported as offset to read that passage in its natural paragraph flow, instead of grep's flat per-line output."
        book_title = runtime.state.get("book_title")
        title = get_book_path(book_title)
        with open(f"data/{title}/{title}_book_content.md", "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(offset - 1, 0)
        selected = lines[start:start + limit]
        return "".join(f"{i}\t{line}" for i, line in enumerate(selected, start=offset))

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"src/skills/content_skills/script_drafter_agent/{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[dict] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs("src/skills/content_skills/script_drafter_agent", exist_ok=True)
        all_skills = list(Path("src/skills/content_skills/script_drafter_agent").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"