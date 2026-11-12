from podcast_generation.settings import DATA_DIR
from pathlib import Path
from typing import Any
import glob
import os

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent, AgentState
from langgraph.runtime import Runtime
from langchain_core.messages import HumanMessage

from langchain.agents.middleware import ModelFallbackMiddleware, AgentMiddleware, after_agent
from deepagents import FilesystemMiddleware
from deepagents.backends import FilesystemBackend

from openrouter import OpenRouter
from openrouter.components import (
    # request side
    DecisionsRequest, Questions, State,
    DecisionsNoulQuestion, DecisionsNoulQuestionTypedDict,
    # response side
    DecisionsResponse,
    DecisionsNoulAnswer,
)

from .state import ScriptPlannerState
from ...models import SCRIPT_PLANNER_MODEL, track, DECISION_JUDGE
from ..utils import checkpointer, get_book_path


with open(Path(__file__).parent / "prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

script_planner_model = ChatOpenRouter(
    model=SCRIPT_PLANNER_MODEL,
    temperature=0.3,
)

file_manager_middleware = FilesystemMiddleware(
    backend=FilesystemBackend(str(DATA_DIR)),
    tools=["edit_file", "ls", "read_file", "write_file", "glob", "grep"],
    tool_token_limit_before_evict=30_000
)

ARTIFACT_FILENAME = "script_plan.md"   # the planner's output, under data/<book slug>/
BOOK_FILENAME = "book_content.md"      # the source the plan's line citations point into
MAX_VERIFY_ATTEMPTS = 3
READY_THRESHOLD = 0.6
MAX_JUDGE_CHARS = 60_000

READY_CRITERIA = (
    "The artifact is a complete podcast segment plan: an episode thesis, cold open "
    "candidates, setup, several main segments, a turn (counterargument), a practical "
    "close and outro takeaways. Each main segment states one core idea and lists "
    "supporting evidence in its own words, specific and self-contained (the names, "
    "numbers, findings and, for stories, the steps), so a writer could draft from it "
    "without opening the book. Every evidence item, and every book-derived "
    "fact in the other sections, ends with a line citation such as [L120] or [L120-135] "
    "(several allowed: [L45, L120-135]). Citations are narrow ranges (a few lines, rarely "
    "more than about thirty, never a whole chapter), have a start no greater than their "
    "end, and fall between line 1 and book_total_lines. Nothing is uncited unless it is "
    "explicitly marked '(not from the book)'. The plan contains no dialogue script, "
    "placeholders, TODOs, a leftover '<!-- END OF PLAN -->' marker, truncated or "
    "cut-off sections, tool error messages, or assistant chatter."
)

READY_NOT_CRITERIA = (
    "The artifact is empty, unfinished or cut off, is missing required sections or has "
    "segments without a clear single core idea, has vague evidence that only points at a "
    "topic ('the book discusses X') without the actual content, has evidence items or facts with no line "
    "citation, uses citations in the wrong form (page or chapter numbers, a whole chapter "
    "as one range, ranges that run backwards), cites line numbers beyond book_total_lines, "
    "is written as dialogue instead of a plan, or contains placeholders, TODOs, the "
    "'<!-- END OF PLAN -->' marker, error messages or assistant chatter."
)

ARTIFACT_READY_QUESTION: DecisionsNoulQuestionTypedDict = {
    "type": "noul",
    "instructions": (
        "Is this segment plan finished and good for the Script Drafter to follow "
        "as-is, with every piece of book evidence backed by a line-number citation?"
    ),
    "criteria": {
        "true": READY_CRITERIA,
        "false": READY_NOT_CRITERIA,
    },
}


def _send_back(attempts: int, message: str) -> dict[str, Any]:
    """Jump back to the model with feedback, and count the attempt."""
    return {
        "jump_to": "model",
        "verify_attempts": attempts + 1,
        "messages": [HumanMessage(message)],
    }


@after_agent(can_jump_to=["model"], state_schema=ScriptPlannerState)
def verify_artifact(state: ScriptPlannerState, runtime: Runtime) -> dict[str, Any] | None:
    attempts = state.get("verify_attempts", 0)
    book_title = state.get("book_title")
    if attempts >= MAX_VERIFY_ATTEMPTS or not book_title:
        return None  # out of retries, or nothing to locate the artifact by

    path = DATA_DIR / get_book_path(book_title) / ARTIFACT_FILENAME
    if not os.path.exists(path):
        return _send_back(attempts, f"Required file {path} doesn't exist yet. Create it before finishing.")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        return _send_back(attempts, f"{path} exists but is empty. Write its content before finishing.")

    judged_state: dict[str, Any] = {"artifact_path": path, "artifact": content[:MAX_JUDGE_CHARS]}
    # Some books are stored as <name>_book_content.md, so match on the suffix
    book_files = sorted(glob.glob(str(DATA_DIR / get_book_path(book_title) / f"*{BOOK_FILENAME}")))
    if book_files:  # lets the judge flag citations pointing past the end of the book
        with open(book_files[0], "r", encoding="utf-8") as f:
            judged_state["book_total_lines"] = sum(1 for _ in f)
    if len(content) > MAX_JUDGE_CHARS:
        judged_state["note"] = f"Only the first {MAX_JUDGE_CHARS} of {len(content)} characters are shown."

    try:
        with OpenRouter(api_key=os.environ.get("OPENROUTER_API_KEY")) as client:
            res = client.alpha.decisions.create(
                model=DECISION_JUDGE,
                questions={"artifact_ready": ARTIFACT_READY_QUESTION},
                state=judged_state,
            )
    except Exception as err:  # judge outage must not block or loop the agent
        print(f"[verify_artifact] judge call failed, skipping verification: {err}")
        return None

    answer = res.answers.get("artifact_ready")
    if not isinstance(answer, DecisionsNoulAnswer):
        print(f"[verify_artifact] judge gave no yes/no answer ({type(answer).__name__}), skipping verification")
        return None

    if answer.noul >= READY_THRESHOLD:
        return None  # good to go

    return _send_back(
        attempts,
        f"A reviewer judged {path} not ready (P(ready)={answer.noul:.2f}, need >= {READY_THRESHOLD}). "
        f"Re-read it and fix: {READY_CRITERIA} "
        "Then finish again.",
    )


middleware: list[AgentMiddleware[Any, Any, Any]] = [
    file_manager_middleware,
    verify_artifact,
    ModelFallbackMiddleware(
        ChatOpenRouter(model="upstage/solar-pro4", temperature=0.3),
        ChatOpenRouter(model="deepseek/deepseek-v4-flash", temperature=0.3),
    ),
]

script_planner_agent = create_agent(
    script_planner_model,
    state_schema=ScriptPlannerState,
    system_prompt=SYSTEM_PROMPT,
    middleware=middleware,
    checkpointer=checkpointer,
)

script_planner_agent = track(script_planner_agent)