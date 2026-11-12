from podcast_generation.settings import DATA_DIR
import shutil
from pathlib import Path
from typing import Annotated, Literal, Optional

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langgraph.graph import StateGraph, START, END
from langchain.agents.middleware import FilesystemFileSearchMiddleware

from typing_extensions import TypedDict, NotRequired
from pydantic import BaseModel, Field

from ...models import EVALUATOR_MODEL
from ..shared_tools import SharedContentTools
from ..utils import get_book_path


evaluator_model = ChatOpenRouter(model=EVALUATOR_MODEL, temperature=.3, max_tokens=8192)

PROMPT_DIR = Path(__file__).parent / "evaluator_prompts"
FIDELITY_PROMPT = (PROMPT_DIR / "fidelity.md").read_text(encoding="utf-8")
STRUCTURE_PROMPT = (PROMPT_DIR / "structure.md").read_text(encoding="utf-8")
DEPTH_PROMPT = (PROMPT_DIR / "depth.md").read_text(encoding="utf-8")

MAX_ATTEMPTS = 3

# Graph State
class RevisionLoopState(TypedDict):
    book_title: str  

    fidelity_score: Annotated[NotRequired[float], "Scale of 0.0-1.0 based on how much the script reflects the book's true content"]
    fidelity_proof: NotRequired[str]
    fidelity_findings: NotRequired[list[dict]]

    structure_score: Annotated[NotRequired[float], "Scale of 0.0-1.0 how well the script and the conversation is structured"]
    structure_proof: NotRequired[str]
    structure_findings: NotRequired[list[dict]]

    depth_score: Annotated[NotRequired[float], "Scale of 0.0-1.0 how well it reached second examples and mechanisms"]
    depth_proof: NotRequired[str]
    depth_findings: NotRequired[list[dict]]

    integrator_decision: NotRequired[Literal["approved", "needs_revision"]]
    revision_instructions: NotRequired[str]

# Schemas
class Finding(BaseModel):
    location: str = Field(description="Verbatim excerpt (about 15 words max) from the script, unique within it, so an editor can find the spot with an exact match")
    issue: str = Field(description="What is wrong, and which rule or check it breaks")
    evidence: str = Field(description="What the book or the script shows. For book material, quote the matching line or retrieved passage briefly, with its book line number such as [L412] when you have one")
    suggested_fix: str = Field(description="The smallest change that fixes it. Describe it; do not write the new dialogue")
    severity: Literal["high", "medium", "low"]

class FidelitySchema(BaseModel):
    fidelity_score: float | None = Field(description="Scale of 0.0-1.0 based on how much the script reflects the book's true content", le=1.0, ge=0.0)
    fidelity_proof: str = Field(description="Evidence from the script justifying your score")
    findings: list[Finding] = Field(default_factory=list, description="One entry per real problem, most severe first. Empty if the script is faithful")

class StructureSchema(BaseModel):
    structure_score: float | None = Field(description="Scale of 0.0-1.0 how well the script and the conversation is structured", le=1.0, ge=0.0)
    structure_proof: str = Field(description="Evidence from the script justifying your score")
    findings: list[Finding] = Field(default_factory=list, description="One entry per real problem, most severe first. Empty if the structure is sound")

class DepthSchema(BaseModel):
    depth_score: float | None = Field(description="Scale of 0.0-1.0 how well it reached second examples and mechanisms", le=1.0, ge=0.0)
    depth_proof: str = Field(description="Evidence from the script justifying your score")
    findings: list[Finding] = Field(default_factory=list, description="One entry per confirmed gap, most important first. Empty if the episode is deep")

class IntegratorSchema(BaseModel):
    approval: bool = Field(description="True if the script is good enough to be submitted. False if the script needs to be revised by the drafter agent.")
    script_drafter_instruction: Optional[str] = Field(description="If the script needs to be revised, clearly stated TODO for the script drafter the way it should refine the script.", default="")

# Inputs -------------------------------------------------------------------
def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _load_context(book_title: str) -> dict:
    """Everything an evaluator may be shown, read fresh from disk so it sees the latest draft."""
    book_dir = DATA_DIR / get_book_path(book_title)
    book_files = sorted(book_dir.glob("*book_content.md"))  # some books are <name>_book_content.md
    return {
        "script": _read_optional(book_dir / "script.md"),
        "plan": _read_optional(book_dir / "script_plan.md"),
        "expert": _read_optional(book_dir / "expert_persona.md"),
        "host": _read_optional(DATA_DIR / "host_persona.md"),
        "book_file": book_files[0] if book_files else None,
    }


# Tag names for the sections of the evaluator's input. Tags, not markdown headings:
# the persona files and the plan carry their own headings.
_SECTION_TAGS = {
    "plan": ("script_plan", "(No script plan exists for this book. Judge without it.)"),
    "expert": ("expert_persona", "(Expert persona file not found.)"),
    "host": ("host_persona", "(Host persona file not found.)"),
}


def _compose_message(book_title: str, ctx: dict, sections: tuple[str, ...]) -> str:
    # Virtual path as the file search tools see it (their root is the data folder)
    book_path = "/" + ctx["book_file"].relative_to(DATA_DIR).as_posix()
    parts = [f"Book: {book_title}", f"Book file: {book_path}", "", "<draft_script>", ctx["script"], "</draft_script>"]
    for key in sections:
        tag, missing = _SECTION_TAGS[key]
        parts += ["", f"<{tag}>", ctx[key] or missing, f"</{tag}>"]
    return "\n".join(parts)


# Shared runner ------------------------------------------------------------
def _evaluate(state: RevisionLoopState, *, prefix: str, schema, system_prompt: str,
              sections: tuple[str, ...], use_retrieval: bool) -> dict:
    def failed(reason: str) -> dict:
        print(f"[{prefix}_evaluator] {reason}")
        return {f"{prefix}_score": None, f"{prefix}_proof": f"Evaluator did not run: {reason}", f"{prefix}_findings": []}

    # The book is a required input of every evaluator: raise instead of scoring without it.
    book_title = state.get("book_title")
    if not book_title:
        raise ValueError(f"[{prefix}_evaluator] state has no book_title")
    ctx = _load_context(book_title)
    if ctx["book_file"] is None:
        raise FileNotFoundError(
            f"[{prefix}_evaluator] no *book_content.md found in data/{get_book_path(book_title)}/"
        )
    if not ctx["script"] or not ctx["script"].strip():
        return failed(f"no script found at data/{get_book_path(book_title)}/script.md")

    if shutil.which("rg") is None:
        raise RuntimeError(f"[{prefix}_evaluator] ripgrep (rg) is not on PATH; grep_search cannot read the books without it")

    agent = create_agent(
        model=evaluator_model,
        tools=[SharedContentTools.retrieve_info] if use_retrieval else [],
        system_prompt=system_prompt,
        response_format=schema,
        middleware=[
            FilesystemFileSearchMiddleware(root_path=str(DATA_DIR))
        ]
    )
    message = _compose_message(book_title, ctx, sections)

    last_error = "unknown"
    for _ in range(MAX_ATTEMPTS):
        try:
            result = agent.invoke({"messages": [{"role": "user", "content": message}]})
            structured = result.get("structured_response")  # the schema instance lives under this key
            if isinstance(structured, schema):
                return {
                    f"{prefix}_score": getattr(structured, f"{prefix}_score"),
                    f"{prefix}_proof": getattr(structured, f"{prefix}_proof"),
                    f"{prefix}_findings": [f.model_dump() for f in structured.findings],
                }
            last_error = f"no structured response (got {type(structured).__name__})"
        except Exception as err:
            last_error = repr(err)
    return failed(f"gave up after {MAX_ATTEMPTS} attempts: {last_error}")


# Graph nodes --------------------------------------------------------------
def fidelity_evaluator_node(state: RevisionLoopState):
    return _evaluate(state, prefix="fidelity", schema=FidelitySchema, system_prompt=FIDELITY_PROMPT,
                           sections=("plan", "expert"), use_retrieval=True)


def structure_evaluator_node(state: RevisionLoopState):
    return _evaluate(state, prefix="structure", schema=StructureSchema, system_prompt=STRUCTURE_PROMPT,
                           sections=("host", "expert", "plan"), use_retrieval=False)


def depth_evaluator_node(state: RevisionLoopState):
    return _evaluate(state, prefix="depth", schema=DepthSchema, system_prompt=DEPTH_PROMPT,
                           sections=("plan", "expert"), use_retrieval=True)


EVALUATOR_PRIORITY = ("fidelity", "structure", "depth") 


def _format_result(state: RevisionLoopState, prefix: str) -> str | None:
    """The evaluator's result as prompt text, or None if it did not produce a score."""
    score = state.get(f"{prefix}_score")
    if score is None:
        return None
    findings = "\n".join(
        "- " + "; ".join(f"{key}: {value}" for key, value in finding.items())
        for finding in state.get(f"{prefix}_findings") or []
    ) or "None"
    return f"Score: {score}\n\nProof for scoring: {state.get(f'{prefix}_proof')}\n\nFindings:\n{findings}"


def feedback_integrator_node(state: RevisionLoopState):

    # Keep only the evaluators that produced a score (a failed one stores None)
    results = {p: r for p in EVALUATOR_PRIORITY if (r := _format_result(state, p)) is not None}
    if not results:
        raise RuntimeError("[feedback_integrator] no evaluator produced a score")

    scores = [state[f"{p}_score"] for p in results]
    if sum(scores) / len(scores) >= 0.8:
        return {"integrator_decision": "approved"}

    results_text = "\n\n".join(f"Results from the {p} evaluator:\n{r}" for p, r in results.items())
    skipped = [p for p in EVALUATOR_PRIORITY if p not in results]
    if skipped:
        results_text += f"\n\nThese evaluators did not run, so there are no results from them: {', '.join(skipped)}"
    
    
    message = f"""
    Given the results from each evaluators' work, I want you to integrate their findings 
    into one task for the script drafter agent. 
    Keep the following order of priority when combining the recommendations: 
    fidelity > structure > depth

    {results_text}
    """

    llm_model = evaluator_model.with_structured_output(IntegratorSchema, strict=True)
    try:
        result = llm_model.invoke(message)
        if isinstance(result, IntegratorSchema):
            if result.approval:
                return {"integrator_decision": "approved"}
            else:
                return {"integrator_decision": "needs_revision", "revision_instructions": result.script_drafter_instruction}
    except Exception as e:
        print(f"[Integrator model failed] Evaluators' feedback could not be pulled together\n{e}")
        return {"integrator_decision": "approved"}


# Compiling the graph ------------------------------------------------------
revision_workflow = StateGraph(state_schema=RevisionLoopState)
revision_workflow.add_node("fidelity_evaluation", fidelity_evaluator_node)
revision_workflow.add_node("structure_evaluation", structure_evaluator_node)
revision_workflow.add_node("depth_evaluation", depth_evaluator_node)
revision_workflow.add_node("feedback_integration", feedback_integrator_node)

revision_graph = (revision_workflow
    .add_edge(START, "fidelity_evaluation")
    .add_edge(START, "structure_evaluation")
    .add_edge(START, "depth_evaluation")
    .add_edge("fidelity_evaluation", "feedback_integration")
    .add_edge("structure_evaluation", "feedback_integration")
    .add_edge("depth_evaluation", "feedback_integration")
    .add_edge("feedback_integration", END)
    .compile()
)