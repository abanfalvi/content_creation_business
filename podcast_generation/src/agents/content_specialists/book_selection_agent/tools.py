from langchain_tavily import TavilySearch, TavilyExtract
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain.tools import tool, ToolRuntime
import json
from dotenv import load_dotenv
from typing import List

from .state import BookSelectionState

load_dotenv()

class BookSelectionTools:
    "List of tools for Book Selection Agent"

    @tool
    @staticmethod
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
    @staticmethod
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
    @staticmethod
    def update_booklist(book_title: str, author: str, abstract: str, genre: str) -> str:
        "Save/Update the wishlist of the booklist file"
        with open("src/book_list.json", "r") as f:
            data = json.load(f)

        if genre in data["list_of_books"]["wishlist"].keys():
            data["list_of_books"]["wishlist"][genre].append({"title": book_title, "author": author, "abstract": abstract, "filepath": ""})
        else:
            data["list_of_books"]["wishlist"][genre] = []
            data["list_of_books"]["wishlist"][genre].append({"title": book_title, "author": author, "abstract": abstract, "filepath": ""})

        with open("src/book_list.json", "w") as f:
            json.dump(data, f, indent=4)

        return "Book list has been updated!"

    @tool
    @staticmethod
    def add_filepath(book_title: str, genre: str, filepath: str):
        "Add filepath to the specific books"
        with open("src/book_list.json", "r") as f:
            data = json.load(f)

        for book in data["list_of_books"]["wishlist"][genre]:
            if book["title"] == book_title:
                book["filepath"] = filepath
                break

        with open("src/book_list.json", "w") as f:
            json.dump(data, f, indent=4)

    @tool
    @staticmethod
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
    @staticmethod
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
