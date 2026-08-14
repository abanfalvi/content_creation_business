from dotenv import load_dotenv
import sqlite3
import opik

from langchain_openrouter import ChatOpenRouter
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents.middleware import FilesystemFileSearchMiddleware

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse, HumanInTheLoopMiddleware, wrap_tool_call
from langgraph.types import Command

from opik.integrations.langchain import OpikTracer, track_langgraph

from .tools import AudioEngineerTools
from .state import AudioEngineerState, RubricScores

load_dotenv()

opik.configure(workspace="dreadnought0073", project_name="podcast_generation")

with open(r"src\agents\production_specialists\prompts\audio_engineer_agent_prompt.md", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

audio_engineer_model = ChatOpenRouter(
    model="xiaomi/mimo-v2.5",
    temperature=0.2,
    # api_key=OPENROUTER_API_KEY
)

all_tools = [
    AudioEngineerTools.listen_audio,
    AudioEngineerTools.adjust_volume,
    AudioEngineerTools.fade,
    AudioEngineerTools.overlay_audio,
    AudioEngineerTools.trim_audio,
    AudioEngineerTools.trim_silence,
    AudioEngineerTools.generate_audio,
    AudioEngineerTools.record_rubric_scores
]


# Create the agent with step-based configuration
conn = sqlite3.connect("./checkpoints/production_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

audio_engineer = create_agent(
    audio_engineer_model,
    tools=all_tools,
    state_schema=AudioEngineerState,
    system_prompt=SYSTEM_PROMPT,
    middleware=[
        FilesystemFileSearchMiddleware(
            root_path="/data",
            use_ripgrep=True,
        ),
    ],
    checkpointer=checkpointer,
    # response_format=RubricScores
)

opik_tracer = OpikTracer()
audio_engineer_agent = track_langgraph(audio_engineer, opik_tracer)