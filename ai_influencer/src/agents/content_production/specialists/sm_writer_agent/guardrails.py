from typing import Any, Optional
from pydantic import BaseModel, Field
from pathlib import Path
import base64

from langchain_openrouter import ChatOpenRouter
from langchain.agents.middleware import after_agent, AgentState
from langgraph.runtime import Runtime
from langchain.messages import AIMessage, HumanMessage

from .....models import SAFETY_MODEL
from .state import ContentCreatorState

class OutputDecisionSchema(BaseModel):
    safe: bool = Field(description="Set this to true if none of them contains NSFW or other harmful content")
    reasoning: Optional[str] = Field(description="Explanation if the content is considered unsafe, otherwise you leave it empty", default="")

class ConsistencyDimension(BaseModel):
    match: bool = Field(description="True if this specific dimension matches the reference character/media, false if it visibly differs")
    evidence: str = Field(description="One concise sentence citing exactly what was compared and why it does or doesn't match")

class ConsistencyRubric(BaseModel):
    face_identity: ConsistencyDimension = Field(description="Core facial identity: face shape, eyes (color/shape/spacing), nose, mouth/lips, cheekbones, jawline, chin — the features a viewer would use to recognize this specific person")
    skin_tone: ConsistencyDimension = Field(description="Skin tone and texture, on both face and any visible body, matches the locked character across lighting/context differences")
    hair: ConsistencyDimension = Field(description="Hair color, texture, and length match (styling/parting may vary if within the character's stated variation range)")
    body_build: ConsistencyDimension = Field(description="Height impression, frame/build, and proportions match; no unexplained change in body type")
    distinguishing_marks: ConsistencyDimension = Field(description="Tattoos, scars, piercings, birthmarks, or freckle clusters are present, correctly placed, and unchanged — none missing, added, or moved")
    consistent: bool = Field(description="Overall verdict: true only if every dimension above matches. Styling, outfit, pose, expression, setting, and lighting are expected to vary across posts and must NOT affect this verdict")
    reasoning: str = Field(description="If not consistent, a concise summary of which dimension(s) failed and why. Leave empty if consistent.", default="")

class CaptionDimension(BaseModel):
    match: bool = Field(description="True if this specific dimension matches the influencer's established persona, false if it visibly differs")
    evidence: str = Field(description="One concise sentence citing exactly what was compared and why it does or doesn't match")

class CaptionRubric(BaseModel):
    voice_and_tone: CaptionDimension = Field(description="The caption's formality, humor style, sentence rhythm, and any signature verbal tics/catchphrases match what's established in PERSONALITY.md's Communication Style & Tone section")
    persona_accuracy: CaptionDimension = Field(description="Any factual claim, opinion, interest, or anecdote referenced in the caption is either already established in PERSONALITY.md/BACKSTORY.md, or is a plausible extension of it — nothing invents a new fact that contradicts the established persona")
    values_alignment: CaptionDimension = Field(description="The caption's framing and any implied opinion is consistent with the influencer's stated core values — it doesn't contradict what she's established to care about or believe")
    consistent: bool = Field(description="Overall verdict: true only if every dimension above matches")
    reasoning: str = Field(description="If not consistent, a concise summary of which dimension(s) failed and why. Leave empty if consistent.", default="")

safety_model = ChatOpenRouter(
    model=SAFETY_MODEL,
    temperature=0.2,
    max_tokens=2048,
    timeout=120000
)

caption_reviewer_model = ChatOpenRouter(
    model=SAFETY_MODEL,
    temperature=0.3,
    max_tokens=4096,
    timeout=120000
)

structured_safety_model = safety_model.with_structured_output(OutputDecisionSchema, method="json_schema", strict=True)
structured_consistency_model = safety_model.with_structured_output(ConsistencyRubric, method="json_schema", strict=True)
structured_caption_model = caption_reviewer_model.with_structured_output(CaptionRubric, method="json_schema", strict=True)

@after_agent(can_jump_to=["model"])
def safe_output_guardrail(state: ContentCreatorState, runtime: Runtime) -> dict[str, Any] | None:
    """LLM checks if the image/video & caption does not contain NSFW or harmful content"""
    influencer_name = state.get("influencer_name")
    with open(f"src/influencers/{influencer_name}/social_contents/CAPTION.md", "r", encoding="utf-8") as f:
        caption = f.read()

    is_video = bool(state.get("video_url"))
    media_type = "video" if is_video else "image"
    mime_type = "video/mp4" if is_video else "jpeg"
    new_url = state.get("video_url") if is_video else state.get("img_url")

    # Use a model to evaluate safety
    safety_prompt = HumanMessage(content=[
        {"type": "text", "text": 
                f"""Evaluate if these {media_type} and caption do not contain NSFW and are harmless and do not give any form of advice.
                Respond according to the provided schema.
            
                Caption: {caption}"""},
        {
            "type": media_type,
            "url": new_url,
            "mime_type": mime_type,
        },
    ])

    result = structured_safety_model.invoke([safety_prompt])

    if not result.safe:
        return {
            "jump_to": "model",
            "messages": [
                HumanMessage(content=(
                    "The most recently generated content was flagged by the safety review "
                    f"and cannot be published. Reason: {result.reasoning}. "
                    "Revise your work — regenerate the image/video and/or rewrite the caption — "
                    "so it no longer contains this issue, then finish again."
                ))
            ],
        }
    return None

@after_agent(can_jump_to=["model"])
def consistency_check_guardrail(state: ContentCreatorState, runtime: Runtime) -> dict[str, Any] | None:
    """LLM checks if the produced image/video is still consistent with the last 4 previously generated ones"""
    influencer_name = state.get("influencer_name")
    media_content_path = f"src/influencers/{influencer_name}/social_contents"

    # Use a model to evaluate consistency
    with open(f"src/influencers/{influencer_name}/CHARACTER.md", "r", encoding="utf-8") as f:
        character = f.read()

    is_video = bool(state.get("video_url"))
    media_type = "video" if is_video else "image"
    mime_type = "video/mp4" if is_video else "jpeg"
    new_url = state.get("video_url") if is_video else state.get("img_url")

    def convert_media_to_base64(file: Path):
        with open(file, "rb") as f:
            data = base64.b64encode(f.read()).decode(encoding="utf-8")
        return data

    ext = "*.mp4" if is_video else "*.jpg"
    subfolder = "videos" if is_video else "images"
    history_files = sorted(Path(f"{media_content_path}/{subfolder}").glob(ext))[-5:-1]
    history_files = [convert_media_to_base64(file) for file in history_files]

    safety_prompt = HumanMessage(content=[
        {"type": "text", "text": 
                f"""Evaluate if these {media_type} and the predetermined
                character description are consistent with the newly created video content.
                Respond according to the provided schema.
                
                Character description:\n{character}"""},
        {"type": "text", "text": "NEW CONTENT TO EVALUATE:"},
        {"type": media_type, "url": new_url, "mime_type": mime_type},
        {"type": "text", "text": "PREVIOUSLY PUBLISHED REFERENCE CONTENT (for comparison only — do not evaluate these, only the item above):"},
        *[{
            "type": media_type,
            "base64": file,
            "mime_type": mime_type,
        } for file in history_files],
    ])

    result = structured_consistency_model.invoke([safety_prompt])

    if not result.consistent:
        return {
            "jump_to": "model",
            "messages": [
                HumanMessage(content=(
                    "Your proposed content was flagged by the inconsistency review "
                    f"and cannot be published. Reason: {result.reasoning}. "
                    "Revise your work — regenerate the image/video with more precise prompts — "
                    "so it will look more consistent to the previous media contents, then finish again."
                ))
            ],
        }
    return None

@after_agent(can_jump_to=["model"])
def check_caption_consistency(state: ContentCreatorState, runtime: Runtime) -> dict[str, Any] | None:
    """LLM checks if the caption's voice, claims, and values are consistent with PERSONALITY.md and BACKSTORY.md"""
    influencer_name = state.get("influencer_name")
    caption_path = f"src/influencers/{influencer_name}/social_contents/CAPTION.md"
    personality_path = f"src/influencers/{influencer_name}/PERSONALITY.md"
    backstory_path = f"src/influencers/{influencer_name}/BACKSTORY.md"

    with open(caption_path, "r", encoding="utf-8") as f:
        caption = f.read()

    with open(personality_path, "r", encoding="utf-8") as f:
        personality = f.read()

    with open(backstory_path, "r", encoding="utf-8") as f:
        backstory = f.read()

    review_prompt = f"""Evaluate whether the newly written caption is consistent with the influencer's
    established voice, personality, and backstory. Respond according to the provided schema.

    Caption:
    {caption}

    Personality:
    {personality}

    Backstory:
    {backstory}"""

    result = structured_caption_model.invoke([HumanMessage(content=review_prompt)])

    if not result.consistent:
        return {
            "jump_to": "model",
            "messages": [
                HumanMessage(content=(
                    "Your caption was flagged by the persona-consistency review "
                    f"and cannot be published. Reason: {result.reasoning}. "
                    "Revise the caption so it matches her established voice and doesn't "
                    "introduce or contradict any persona fact, then finish again."
                ))
            ],
        }
    return None