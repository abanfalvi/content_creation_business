from langchain_tavily import TavilySearch, TavilyExtract
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
from langchain_cohere import CohereRerank
from langchain_classic.retrievers.contextual_compression import (
    ContextualCompressionRetriever,
)
import json
from dotenv import load_dotenv
from typing import List

from .state import BookSelectionState, ExpertBuilderState, ScriptDrafterState
from ...vector_db import vector_store

load_dotenv()

def get_book_path(book_title: str):
    symbols = [":", " ", ","]
    for symbol in symbols:
        book_title = book_title.replace(symbol, "_")
        book_title = book_title.replace("__", "_")
    title = book_title.lower()
    return title

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
        for topic, books in data["list_of_books"]["whislist"].items():
            for book in books:
                if book["title"] == book_title:
                    data["list_of_books"]["finished"][topic].append(book)
                    books.remove(book)
        return f"{book_title} has been moved to 'Finished' status!"

class ExpertProfileTools:

    @tool
    def read_persona(book_title: str, runtime: ToolRuntime[None, ExpertBuilderState]):
        "Read the expert persona that has been drafted so far"
        title = get_book_path(book_title)
        with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
            persona_content = f.read()
        return Command(update={
            "messages": [ToolMessage(content=persona_content, tool_call_id=runtime.tool_call_id)],
            "persona_read": True,
        })

    @tool
    def edit_persona(book_title: str, to_replace: str, replace_with: str, runtime: ToolRuntime[None, ExpertBuilderState]):
        "Edit the expert persona in certain parts"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
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
    def append_persona(book_title: str, content: str, runtime: ToolRuntime[None, ExpertBuilderState]):
        "Add further information to the end of the document about the expert persona"
        if not runtime.state.get("persona_read"):
            return "Error: you must call read_persona before editing. Call it now."
        title = get_book_path(book_title)

        with open(f"data/{title}/expert_persona.md", "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} - has been appended to the expert profile persona!"

    @tool
    def retrieve_info(query: str):
        "Retrieve information to understand the content of the book"
        retriever = vector_store.as_retriever(k=20)
        compressor = CohereRerank(model="rerank-v4.0-fast", top_n=5) 
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor, base_retriever=retriever
        )
        compressed_docs = compression_retriever.invoke(
            query
        )
        return compressed_docs

class ScriptDrafterTools:

    @tool
    def read_script(book_title: str, runtime: ToolRuntime[None, ScriptDrafterState]):
        "Read the content of the script draft"
        title = get_book_path(book_title)
        with open(f"data/{title}/script.md", "r", encoding="utf-8") as f:
            script_content = f.read()
        return Command(update={
            "messages": [ToolMessage(content=script_content, tool_call_id=runtime.tool_call_id)],
            "script_read": True,
        })

    @tool
    def edit_script(book_title: str, to_replace: str, replace_with: str, runtime: ToolRuntime[None, ScriptDrafterState]):
        "Edit the podcast script in specific parts"
        if not runtime.state.get("script_read"):
            return "Error: you must call read_script before editing. Call it now."
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
    def append_script(book_title: str, content: str, runtime: ToolRuntime[None, ScriptDrafterState]):
        "Add further information/extend the script"
        if not runtime.state.get("script_read"):
            return "Error: you must call read_script before editing. Call it now."
        title = get_book_path(book_title)

        with open(f"data/{title}/script.md", "a", encoding="utf-8") as f:
            f.write(content)

        return f"{content} - has been appended to the script!"

    @tool
    def read_personas(book_title: str, host: bool = True):
        "Read the personas that were created: Host or Expert. It will only return either personas based on the input parameters"
        if host:
            with open("data/host_persona.md", "r", encoding="utf-8") as f:
                host_persona = f.read()
            return host_persona
        else:
            title = get_book_path(book_title)
            with open(f"data/{title}/expert_persona.md", "r", encoding="utf-8") as f:
                expert_persona = f.read()
            return expert_persona