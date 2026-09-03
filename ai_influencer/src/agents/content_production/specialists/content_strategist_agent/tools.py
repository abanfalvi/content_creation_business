from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, time, httpx, uuid, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import date, timedelta
import threading
from pydantic import BaseModel, Field

from ...utils import FileEditingTools
from .state import ContentPlanningState
from .....models import MEMORY_MANAGEMENT_MODEL

load_dotenv()

_calendar_lock = threading.Lock()

class PersonalityFeatures(BaseModel):
    core_values: List[str] = Field(
        description="The influencer's core values and driving motivations, condensed to short planner-usable phrases (e.g. 'consistency over intensity', 'community over clout')."
    )
    personality_traits: List[str] = Field(
        description="The influencer's most defining personality traits, including quirks and flaws (e.g. 'competitive in a quiet way', 'over-apologizes')."
    )
    communication_style: List[str] = Field(
        description="Notable tone, humor style, pacing, and signature verbal tics/phrases that content should reflect (e.g. recurring phrases, how captions typically open/close)."
    )
    relational_style: List[str] = Field(
        default_factory=list,
        description="How the influencer engages with fans/followers by default — DM/comment tone, boundary style."
    )
    hard_constraints: List[str] = Field(
        description="Things the influencer must never do or say in content — drawn from Triggers/Hard No's, Exclusions/Negative Constraints, and Compliance Notes."
    )

class BackstoryFeatures(BaseModel):
    key_facts: List[str] = Field(
        description="Fixed, non-negotiable facts a content planner must never contradict (e.g. name, age, hometown, occupation) — pulled from Identity Snapshot / Consistency Anchors sections."
    )
    life_highlights: List[str] = Field(
        description="The most content-relevant formative events from the life timeline and signature anecdotes (e.g. a pivotal career moment, a recurring running joke)."
    )
    relationships: List[str] = Field(
        default_factory=list,
        description="Family, friends, or pets worth referencing directly in content, with the detail that makes them usable (e.g. names, how they met, their role)."
    )
    content_angles: List[str] = Field(
        description="Recurring interests, hobbies, or life details that make good recurring content pillars or themes (e.g. running logs, morning routine, coffee order)."
    )
    recurring_rhythms: List[str] = Field(
        default_factory=list,
        description="Daily, weekly, or seasonal patterns useful for scheduling content (e.g. weekday morning workout window, weekend hikes, seasonal shifts)."
    )
    hard_constraints: List[str] = Field(
        description="Things the influencer's backstory must never imply — drawn from Exclusions/Negative Constraints and Compliance Notes (e.g. no real institutions, no elite credentials)."
    )

class InfluencerEvent(BaseModel):
    date: str = Field(description="The calendar date this beat happens on, YYYY-MM-DD.")
    beat: Literal["setup", "development", "complication", "payoff", "standalone"] = Field(
        description="This beat's role in the week's arc. 'setup' introduces something the week will follow; "
        "'development'/'complication' carry it forward or add a wrinkle; 'payoff' resolves an earlier setup; "
        "'standalone' is a beat that doesn't need continuity (use sparingly — most days should connect to something)."
    )
    what_happens: str = Field(
        description="The concrete thing happening to/for the influencer this day — specific enough to hand "
        "straight to a calendar entry's `idea`/`notes`, not a vague mood or topic."
    )
    grounded_in: List[str] = Field(
        description="The specific PERSONALITY.md/BACKSTORY.md detail(s) this beat is built on — same grounding "
        "requirement the planning Operating Principles already enforce per entry, just captured earlier."
    )
    callback_to: Optional[str] = Field(
        default=None,
        description="If this beat pays off, references, or escalates an earlier beat in this same journey, the "
        "date (YYYY-MM-DD) of that beat and a one-line note on the connection. None for 'setup' beats.",
    )
    suggested_content_type: Optional[Literal["image", "video", "text"]] = Field(
        default=None, description="A hint for the format that best fits this beat; the calendar-entry step may override it."
    )


class InfluencerJourney(BaseModel):
    theme: str = Field(
        description="The one-sentence throughline for the whole week — the single arc every beat serves, "
        "e.g. 'training for her first 10k despite hating mornings.' Every InfluencerEvent should visibly serve this."
    )
    week_start: str = Field(description="The first date this journey covers, YYYY-MM-DD.")
    arc: List[InfluencerEvent] = Field(
        description="1-3 beats per day across the 7-day window, ordered chronologically. Beats should reference "
        "each other (via callback_to) often enough that reading the week in order reads as one story, not seven "
        "unrelated ideas that happen to share a theme."
    )


class AgentTools:

    @tool
    def add_calendar_entry(date: str, idea: str, content_type: Literal["image", "video", "text"], platforms: List[Literal["instagram", "thread"]], runtime: ToolRuntime[None, ContentPlanningState], notes: str = "") -> str:
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
    def edit_calendar_entry(date: str, id: str, runtime: ToolRuntime[None, ContentPlanningState], idea: Optional[str] = None, content_type: Optional[Literal["image", "video", "text"]] = None, platforms: Optional[List[Literal["instagram", "thread"]]] = None, notes: Optional[str] = None, caption: Optional[str] = None, asset_filenames: Optional[List[str]] = None):
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
    def read_persona_info(identity: Literal["PERSONALITY", "BACKSTORY"], runtime: ToolRuntime[None, ContentPlanningState]) -> str:
        "Read the influencer's PERSONALITY.md or BACKSTORY.md file content"
        influencer_name = runtime.state.get("influencer_name")

        stored_persona_info = runtime.store.get(("content_production", influencer_name), identity.lower())
        if stored_persona_info:
            return json.dumps(stored_persona_info.value)

        persona_path = f"src/influencers/{influencer_name}/{identity}.md"

        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()

        # Extract the key aspects from it and save it for long term
        schema = PersonalityFeatures if identity == "PERSONALITY" else BackstoryFeatures
        extracter_model = ChatOpenRouter(model=MEMORY_MANAGEMENT_MODEL, temperature=.2)
        extraction_prompt = f"Based on the provided schema, fill in the sections with the information about this influencer. Fill in those that you found information about:\n\n {persona}"

        result = extracter_model.with_structured_output(schema=schema, method="json_schema").invoke(extraction_prompt)
        runtime.store.put(
            ("content_production", influencer_name,),
            identity.lower(),
            result.model_dump(),
        )

        return persona

    @tool
    def get_current_date() -> str:
        "Get today's date as a YYYY-MM-DD string"
        return str(date.today())

    @tool
    def save_influencer_journey(journey: InfluencerJourney, runtime: ToolRuntime[None, ContentPlanningState]):
        "Save the journey the influencer is going to take in the next 7 days"
        influencer_name = runtime.state.get("influencer_name")
        today = date.today()

        [runtime.store.put(
            (influencer_name, "influencer_journey", journey.theme),
            str(today+timedelta(days=idx)),
            {"date": event.date,
             "beat": event.beat,
             "what_happens": event.what_happens,
             "grounded_in": event.grounded_in,
             "callback_to": event.callback_to,
             "suggested_content_type": event.suggested_content_type,
             },
        ) for idx, event in enumerate(journey.arc)]

    @tool
    def load_influencer_journey(runtime: ToolRuntime[None, ContentPlanningState]) -> str:
        "Load the saved journey to use it when writing the content calendar"
        influencer_name = runtime.state.get("influencer_name")
        result = runtime.store.search((influencer_name, "influencer_journey"))

        return "\n\n".join(
            f"Theme of this journey entry: {item.namespace[-1]}\n"
            f"Period: {item.key}\n"
            f"Content: {json.dumps(item.value)}"
            for item in result
        )

    @tool
    def content_strategy(runtime: ToolRuntime[None, ContentPlanningState], edit: bool = True, strategy: str = ""):
        "Read or edit the content strategy for this influencer. Provide the strategy parameter only if you want to edit/append new content."
        influencer_name = runtime.state.get("influencer_name")
        filepath = f"src/influencers/{influencer_name}/CONTENT_STRATEGY.md"
        if edit:
            return FileEditingTools.append_filecontent(strategy, filepath)
        else:
            return FileEditingTools.read_file(filepath)


        