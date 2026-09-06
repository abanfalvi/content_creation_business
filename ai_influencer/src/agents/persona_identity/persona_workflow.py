
from dotenv import load_dotenv
import os
import base64
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Tuple
from openrouter import utils, OpenRouter

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore
from langchain_core.runnables import RunnableConfig
from langchain_openrouter import ChatOpenRouter
from langgraph.config import get_stream_writer

from langgraph.types import interrupt

from opik.integrations.langchain import OpikTracer, track_langgraph

from .specialists.backstory_agent.agent import backstory_agent
from .specialists.character_design_agent.agent import character_design_agent
from .specialists.personality_agent.agent import personality_agent
from .utils import checkpointer
from .workflow_state import PersonaWorkflowState
from ...models import IDENTITY_MANAGER, IMAGE_GEN_MODEL, IMAGE_PROMPT_GEN_MODEL, PERSONA_FALLBACK_MODEL_1, PERSONA_FALLBACK_MODEL_2
from ...auditor.tools import AgentTools
from ...auditor.agent import auditor_agent
from ...memory_store import shared_memory_store

from langgraph.graph import StateGraph, START, END

load_dotenv()

opik_tracer = OpikTracer()

class ReviewSelection(BaseModel):
    agent_to_review: Literal["backstory_agent", "personality_agent", "character_design_agent"] = Field(description="Select the backstory agent if the feedback is related to the interests, relationship or life narrative (backstory). Select the personality agent if the feedback is related to the influencer's inner values (personality). Select the character design agent if the feedback concerns the visual identity of the influencer.")

class PromptsSchema(BaseModel):
    prompts: List[str] = Field(max_length=4)

def call_specialist_agent(agent: Literal["backstory_agent", "personality_agent", "character_design_agent"], prompt: str, thread_id: str, influencer_name: Optional[str] = None, feedback: str = "") -> str | Tuple[str, str]:
    if feedback:
        prompt += f"\n\n Your work has been reviewed and you received the following feedback to refine your work.\n{feedback}"
    if agent == "backstory_agent":
        backstory_result = backstory_agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "influencer_name": influencer_name,
                "artifact": "BACKSTORY"
            },
            config={"configurable": {"thread_id": thread_id}},
        )

        return backstory_result["messages"][-1].content
    elif agent == "personality_agent":
        personality_result = personality_agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "influencer_name": influencer_name,
                "artifact": "PERSONALITY"
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        return personality_result["messages"][-1].content, personality_result.get("voice_name")
    elif agent == "character_design_agent":
        character_result = character_design_agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "artifact": "CHARACTER"
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        return character_result["messages"][-1].content, character_result.get("influencer_name")

def generate_sample_images(prompts: List[str], influencer_name: str) -> None:
    full_output_path = f"src/influencers/{influencer_name}/img"
    os.makedirs(full_output_path, exist_ok=True)
    with OpenRouter(api_key=os.getenv("OPENROUTER_API_KEY", "")) as open_router:
        for idx, prompt in enumerate(prompts):
            res = open_router.images.generate(
                model=IMAGE_GEN_MODEL,
                prompt=prompt,
                n=1,
                aspect_ratio="1:1",
                output_format="jpeg",
                timeout_ms=60000,
                retries=utils.RetryConfig("backoff", utils.BackoffStrategy(500, 5000, 1.5, 30000), False),
            )
            image_bytes = base64.b64decode(res.data[0].b64_json)
            with open(f"{full_output_path}/sample_{idx+1}.jpg", "wb") as f:
                f.write(image_bytes)

def gen_image_node(state: PersonaWorkflowState) -> dict:
    prompt_gen_model = ChatOpenRouter(
        model=IMAGE_PROMPT_GEN_MODEL,
        temperature=0.5
    )
    structured_model = prompt_gen_model.with_structured_output(schema=PromptsSchema, method="json_schema").with_fallbacks([
        ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_1, temperature=0.5).with_structured_output(schema=PromptsSchema, method="json_schema"),
        ChatOpenRouter(model=PERSONA_FALLBACK_MODEL_2, temperature=0.5).with_structured_output(schema=PromptsSchema, method="json_schema"),
    ])
    outcome = structured_model.invoke(f"Provide 4 different prompts for image generation strictly using the provided character description. The character should be in different surroundings, clothes, positions, etc..., so make sure there is enough variety. The person's look should always be the same, so the differences should be in the context and position.\n\n Character description:\n{state.get("character")}")
    generate_sample_images(prompts=outcome.prompts, influencer_name=state.get("influencer_name"))
    return {}

def call_character_design_agent_node(state: PersonaWorkflowState, *, config: RunnableConfig) -> dict:
    get_stream_writer()({"step": "call_character_design_agent"})

    thread_id = f"{config['configurable']['thread_id']}:character_design_agent"
    prompt = state.get("prompt") or "Create the character design of the next influencer"
    human_feedback = state.get("feedback")
    _, influencer_name = call_specialist_agent("character_design_agent", prompt, thread_id, feedback=human_feedback)
    influencer_name = influencer_name.strip().lower().replace(" ", "_")
    with open(f"src/influencers/{influencer_name}/CHARACTER.md", "r", encoding="utf-8") as f:
        character_description = f.read()
    return {"influencer_name": influencer_name, "character": character_description}

def call_personality_agent_node(state: PersonaWorkflowState, *, config: RunnableConfig) -> dict:
    get_stream_writer()({"step": "call_personality_agent"})

    thread_id = f"{config['configurable']['thread_id']}:personality_agent"
    prompt = "Create the personality of the next influencer"
    human_feedback = state.get("feedback")
    _, voice_name = call_specialist_agent("personality_agent", prompt, thread_id, state.get("influencer_name"), feedback=human_feedback)
    with open(f"src/influencers/{state.get("influencer_name")}/PERSONALITY.md", "r", encoding="utf-8") as f:
        personality_description = f.read()
    return {"personality": personality_description, "voice_name": voice_name}

def call_backstory_agent_node(state: PersonaWorkflowState, *, config: RunnableConfig) -> dict:
    get_stream_writer()({"step": "call_backstory_agent"})

    thread_id = f"{config['configurable']['thread_id']}:backstory_agent"
    prompt = "Create the backstory of the next influencer"
    human_feedback = state.get("feedback")
    _ = call_specialist_agent("backstory_agent", prompt, thread_id, state.get("influencer_name"), feedback=human_feedback)
    with open(f"src/influencers/{state.get("influencer_name")}/BACKSTORY.md", "r", encoding="utf-8") as f:
        backstory_description = f.read()
    return {"backstory": backstory_description}

def human_review_node(state: PersonaWorkflowState) -> dict:
    decision = interrupt({
        "message": "Review the finished influencer persona before ending the task.",
        "character": state.get("character"),
        "personality": state.get("personality"),
        "backstory": state.get("backstory"),
    })
    if decision["approved"]:
        return {"status": "approved"}
    return {"status": "needs_revision", "feedback": decision.get("feedback")}

def call_review_router_node(state: PersonaWorkflowState) -> dict:
    review_router_model = ChatOpenRouter(
        model=IDENTITY_MANAGER,
        temperature=0.1,
        max_tokens=1024
    )
    structured_model = review_router_model.with_structured_output(schema=ReviewSelection, method="json_schema")
    decision = structured_model.invoke(f"Decide which agent should work on the feedback and review its work. The following feedback received:\n\n{state.get("feedback")}")
    return {"agent_to_review": decision.agent_to_review}

def lessons_learned_node(state: PersonaWorkflowState, *, store: BaseStore, config: RunnableConfig) -> dict:
    all_traces = {}
    for (name, agent) in [
        ("character_design_agent", character_design_agent),
        ("personality_agent", personality_agent),
        ("backstory_agent", backstory_agent),
    ]:
        agent_thread_id = f"{config['configurable']['thread_id']}:{name}"

        traces = AgentTools.extract_learnable_traces(thread_id=agent_thread_id, agent=agent, active_agent=name)
        result = auditor_agent.invoke({"messages": [("user", f"""
                    Analyse the following traces from {name} by collecting the steps that were successully
                    taken to solve the next part of the question AND should serve as a reinforcing
                    example of how this question/issue should be solved. 
                    In addition, make sure to collect those steps where the agent had troubles/failed
                    to successfully, or smoothly, solve the part of the question/issue at hand AND should
                    serve as a learning trace of what should be avoided in the future. 
        
                    Traces collected for this run: {traces}

                    Followingly, return back a summary of the traces you saved to the user.
        """)],
            "influencer_name": state.get("influencer_name"),
            "department_name": "persona_identity",
            "active_step": "save_traces"
        })
        all_traces[name] = result["messages"][-1].content

    return {"lessons_learned": all_traces}

def routing_function(state: PersonaWorkflowState) -> str:
    agent = state["agent_to_review"]
    if agent == "character_design_agent":
        return "call_character_design_agent"
    elif agent == "personality_agent":
        return "call_personality_agent"
    elif agent == "backstory_agent":
        return "call_backstory_agent"
    raise ValueError(f"Unknown agent_to_review: {agent!r}")

def after_character_design(state: PersonaWorkflowState) -> list[str]:
    if state.get("agent_to_review") == "character_design_agent":
        return ["human_review", "gen_image_samples"]
    return ["call_personality_agent", "call_backstory_agent", "gen_image_samples"]

builder = StateGraph(PersonaWorkflowState)
builder.add_node("call_character_design_agent", call_character_design_agent_node)
builder.add_node("call_personality_agent", call_personality_agent_node)
builder.add_node("call_backstory_agent", call_backstory_agent_node)
builder.add_node("human_review", human_review_node)
builder.add_node("call_review_router", call_review_router_node)
builder.add_node("gen_image_samples", gen_image_node)
builder.add_node("lessons_learned_path", lessons_learned_node)

builder.add_edge(START, "call_character_design_agent")
builder.add_conditional_edges(
    "call_character_design_agent",
    after_character_design,
    ["call_personality_agent", "call_backstory_agent", "human_review", "gen_image_samples"],
    )
builder.add_edge("gen_image_samples", END)
builder.add_edge("call_personality_agent", "human_review")
builder.add_edge("call_backstory_agent", "human_review")

builder.add_conditional_edges(
    "human_review", 
    lambda state: "lessons_learned_path" if state["status"] == "approved" else "call_review_router",
    )
builder.add_conditional_edges(
    "call_review_router",
    routing_function,
    ["call_character_design_agent", "call_personality_agent", "call_backstory_agent"],
    )
builder.add_edge("lessons_learned_path", END)

persona_gen_graph = builder.compile(checkpointer, store=shared_memory_store)

persona_gen_workflow = track_langgraph(persona_gen_graph, opik_tracer)