from dotenv import load_dotenv
import opik
from typing import Callable

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langchain.agents.middleware import FilesystemFileSearchMiddleware

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import AudioEngineerTools
from .state import AudioEngineerState
from ..models import AUDIO_ENGINEER_MODEL
from .utils import checkpointer

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation", install_mcp=False)

with open(r"src\agents\production_specialists\prompts\audio_engineer_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

with open(r"src\agents\production_specialists\prompts\audio_engineer_review_prompt.md", "r", encoding="utf-8") as f:
    REVIEW_PROMPT = f.read()

audio_engineer_model = ChatOpenRouter(
    model=AUDIO_ENGINEER_MODEL,
    temperature=0.2,
    # api_key=OPENROUTER_API_KEY
    timeout=180000,  # ms — httpx's 5s client default isn't enough to upload a multi-MB base64 audio payload
)

all_tools = [
    AudioEngineerTools.listen_audio,
    AudioEngineerTools.adjust_volume,
    AudioEngineerTools.fade,
    AudioEngineerTools.overlay_audio,
    AudioEngineerTools.trim_audio,
    AudioEngineerTools.trim_silence,
    AudioEngineerTools.generate_audio,
    AudioEngineerTools.record_rubric_scores,
    AudioEngineerTools.load_available_skills,
    AudioEngineerTools.load_skill_content
]

STEP_CONFIG = {
    "edit_audio": {
        "prompt": "",
        "tools": [t for t in all_tools if t is not AudioEngineerTools.record_rubric_scores],
        "requires": [],
    },
    "score_final_result": {
        "prompt": REVIEW_PROMPT,
        "tools": [AudioEngineerTools.record_rubric_scores],
        "requires": [],
    },
    
}

@wrap_model_call
def apply_step_config(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Configure agent behavior based on the current step."""
    active_agent = request.state.get("active_step")
    
    # Look up step configuration
    stage_config = STEP_CONFIG[active_agent]

    # Validate required state exists
    for key in stage_config["requires"]:
        if request.state.get(key) is None:
            raise ValueError(f"{key} must be set before reaching {active_agent}")

    step_prompt = stage_config["prompt"].format(
        **request.state
        )

    # Inject system prompt and step-specific tools
    if step_prompt:
        print("System prompt changed")
        request = request.override(
            system_prompt=step_prompt,
            tools=stage_config["tools"],
        )
    else:
        request = request.override(
            tools=stage_config["tools"],
        )

    return handler(request)

audio_engineer = create_agent(
    audio_engineer_model,
    tools=all_tools,
    state_schema=AudioEngineerState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        apply_step_config,
        FilesystemFileSearchMiddleware(
            root_path="data",
            use_ripgrep=True,
        ),
    ],
    checkpointer=checkpointer,
    # response_format=RubricScores
)

opik_tracer = OpikTracer()
audio_engineer_agent = track_langgraph(audio_engineer, opik_tracer)