from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, time, httpx, uuid, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import date
import threading

from ...utils import SkillLoadingTools
from .state import ContentPlanningState

load_dotenv()

_calendar_lock = threading.Lock()

class AgentTools:

    @tool
    def add_calendar_entry(date: str, idea: str, content_type: Literal["image", "video", "text"], platforms: List[Literal["instagram", "tiktok", "thread"]], runtime: ToolRuntime[None, ContentPlanningState], notes: str = "") -> str:
        "Add a new content idea to the influencer's CALENDAR.json under the given date (YYYY-MM-DD). A date may hold multiple entries."
        influencer_name = runtime.state.get("influencer_name")
        calendar_path = f"src/influencers/{influencer_name}/CALENDAR.json"

        with _calendar_lock:
            with open(calendar_path, "r", encoding="utf-8") as f:
                content_calendar = json.load(f)

            content_calendar.setdefault(date, []).append({
                "id": str(uuid.uuid4()),
                "theme": idea,
                "content_type": content_type,
                "platforms": platforms,
                "status": "PLANNED",
                "caption": "",
                "asset_filenames": [],
                "notes": notes
            })

            with open(calendar_path, "w", encoding="utf-8") as f:
                json.dump(content_calendar, f, indent=2)

        return f"Entry has been added successfully for {date}!"

    @tool
    def edit_calendar_entry(date: str, id: str, runtime: ToolRuntime[None, ContentPlanningState], idea: Optional[str] = None, content_type: Optional[Literal["image", "video", "text"]] = None, platforms: Optional[List[Literal["instagram", "tiktok", "thread"]]] = None, notes: Optional[str] = None, caption: Optional[str] = None, asset_filenames: Optional[List[str]] = None):
        "Update one or more fields of an existing CALENDAR.json entry, identified by its date and id. Only the fields you pass are changed."
        influencer_name = runtime.state.get("influencer_name")
        calendar_path = f"src/influencers/{influencer_name}/CALENDAR.json"

        with _calendar_lock:
            with open(calendar_path, "r", encoding="utf-8") as f:
                content_calendar = json.load(f)

            entry = next((e for e in content_calendar.get(date, []) if e["id"] == id), None)
            if entry is None:
                return f"No entry found with id {id} on {date}"

            updates = {"theme": idea, "content_type": content_type, "platforms": platforms, "notes": notes, "caption": caption, "asset_filenames": asset_filenames}
            entry.update({k: v for k, v in updates.items() if v is not None})

            with open(calendar_path, "w", encoding="utf-8") as f:
                json.dump(content_calendar, f, indent=2)

        return f"Entry {id} on {date} updated successfully!"

    @tool
    def list_upcoming_contents(n_contents: int, runtime: ToolRuntime[None, ContentPlanningState]):
        "List the next n_contents calendar entries that have not yet been marked POSTED"
        influencer_name = runtime.state.get("influencer_name")
        calendar_path = f"src/influencers/{influencer_name}/CALENDAR.json"

        with open(calendar_path, "r", encoding="utf-8") as f:
            content_calendar = json.load(f)

        upcoming = [
            {"date": date, **entry}
            for date, entries in content_calendar.items()
            for entry in entries
            if entry["status"] != "POSTED"
        ]

        return f"The following {n_contents} content(s) are coming up next:\n {upcoming[:n_contents]}"

    @tool
    def mark_posted(content_id: str, date: str, runtime: ToolRuntime[None, ContentPlanningState]):
        "Mark the calendar entry with the given id, under the given date, as POSTED"
        influencer_name = runtime.state.get("influencer_name")
        calendar_path = f"src/influencers/{influencer_name}/CALENDAR.json"

        with _calendar_lock:
            with open(calendar_path, "r", encoding="utf-8") as f:
                content_calendar = json.load(f)

            for date_time, content in content_calendar.items():
                if date_time == date:
                    for c in content:
                        if c["id"] == content_id:
                            c["status"] = "POSTED"
                            break

            with open(calendar_path, "w", encoding="utf-8") as f:
                json.dump(content_calendar, f, indent=2)

        return f"{content_id} has been set to POSTED"

    @tool
    def read_persona_info(identity: Literal["PERSONALITY", "BACKSTORY"], runtime: ToolRuntime[None, ContentPlanningState]) -> str:
        "Read the influencer's PERSONALITY.md or BACKSTORY.md file content"
        influencer_name = runtime.state.get("influencer_name")
        persona_path = f"src/influencers/{influencer_name}/{identity}.md"

        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()

        return persona

    @tool
    def get_current_date() -> str:
        "Get today's date as a YYYY-MM-DD string"
        return str(date.today())
        