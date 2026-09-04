from langgraph.types import Command
from langchain_core.messages import ToolMessage, HumanMessage
from langchain.tools import tool, ToolRuntime

from langchain_openrouter import ChatOpenRouter
import wave, io, os, base64, datetime, httpx, uuid, json
from dotenv import load_dotenv
from typing import List, Optional, Literal
from openrouter import OpenRouter, utils
import fal_client
from datetime import date, timedelta
import threading
from pydantic import BaseModel, Field 

from .state import EngagementState
from .guardrails import _passes_moderation

load_dotenv()

_reply_lock = threading.Lock()

MediaInsightMetric = Literal[
    "comments", "crossposted_views", "follows",
    "ig_reels_avg_watch_time", "ig_reels_video_view_total_time", "impressions",
    "likes", "link_clicks", "navigation", "profile_activity", "profile_visits",
    "reach", "reels_skip_rate", "replies", "reposts", "saved", "shares",
    "total_interactions", "views", "total_comments", "total_likes", "total_views",
]

ThreadsMediaInsightMetric = Literal["views", "likes", "replies", "reposts", "quotes", "shares"]

def _get_meta_credentials(influencer_name: str, platform: Literal["instagram", "threads"]) -> tuple[str, str]:
    prefix = influencer_name.upper()
    token = os.getenv(f"{prefix}_{platform.upper()}_ACCESS_TOKEN")
    user_id = os.getenv(f"{prefix}_{platform.upper()}_USER_ID")
    if not token or not user_id:
        raise RuntimeError(f"Missing {platform} credentials for influencer '{influencer_name}'")
    return token, user_id


class AgentTools:

    @tool
    def list_recent_media(platform: Literal["instagram", "threads"], limit: int, runtime: ToolRuntime[None, EngagementState]) -> str:
        "List the influencer's most recent posts on the given platform, newest first, capped at `limit`. Returns each post's id, caption, and permalink as JSON. Use this to find media_ids to check comments or insights for."
        influencer_name = runtime.state.get("influencer_name")
        token, user_id = _get_meta_credentials(influencer_name, platform)
        base = "https://graph.threads.com/v1.0" if platform == "threads" else "https://graph.instagram.com/v25.0"
        field = "id,text,permalink,children,timestamp" if platform == "threads" else "id,caption,permalink,timestamp"
        resp = httpx.get(f"{base}/{user_id}/{'threads' if platform == 'threads' else 'media'}",
                        params={"fields": field, "limit": limit, "access_token": token})
        if resp.is_error or "error" in resp.json():
            raise RuntimeError(f"Failed to list {platform} media: {resp.text}")
        return json.dumps(resp.json().get("data", []))

    @tool
    def get_comments(media_id: str, platform: Literal["instagram", "threads"], runtime: ToolRuntime[None, EngagementState]) -> str:
        "Fetch all top-level comments (and their ids, text, timestamp) on the given post. Comments that fail moderation are filtered out before being returned, so anything you see here is already safe to read and reply to. Returns JSON. Cross-reference against already-replied comment ids before answering."
        influencer_name = runtime.state.get("influencer_name")
        token, _ = _get_meta_credentials(influencer_name, platform)
        base = "https://graph.threads.com/v1.0" if platform == "threads" else "https://graph.instagram.com/v25.0"
        endpoint = f"{base}/{media_id}/replies" if platform == "threads" else f"{base}/{media_id}/comments"
        resp = httpx.get(endpoint, params={"fields": "id,text,timestamp", "access_token": token})
        if resp.is_error or "error" in resp.json():
            raise RuntimeError(f"Failed to fetch comments for {media_id}: {resp.text}")

        comments = resp.json().get("data", [])
        safe_comments = [c for c in comments if _passes_moderation(c.get("text", ""))]
        return json.dumps(safe_comments)

    @tool
    def reply_to_comment(comment_id: str, message: str, platform: Literal["instagram", "threads"], runtime: ToolRuntime[None, EngagementState]) -> Command:
        "Post a public reply to a specific comment id. Only call this once per comment_id — check get_comments and the replied-comments log first to avoid duplicate replies."
        influencer_name = runtime.state.get("influencer_name")
        token, _ = _get_meta_credentials(influencer_name, platform)
        base = "https://graph.threads.com/v1.0" if platform == "threads" else "https://graph.instagram.com/v25.0"
        endpoint = f"{base}/{comment_id}/replies"
        resp = httpx.post(endpoint, data={"message": message, "access_token": token} if platform == "instagram"
                        else {"text": message, "access_token": token})
        if resp.is_error or "error" in resp.json():
            raise RuntimeError(f"Failed to reply to comment {comment_id}: {resp.text}")

        log_path = f"src/influencers/{influencer_name}/engagement/replied_comments.json"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with _reply_lock:
            replied = json.load(open(log_path)) if os.path.exists(log_path) else []
            replied.append({"platform": platform, "comment_id": comment_id, "reply": message, "timestamp": str(datetime.now())})
            json.dump(replied, open(log_path, "w"), indent=2)

        return Command(update={"messages": [ToolMessage(content=f"Replied to comment {comment_id}", tool_call_id=runtime.tool_call_id)]})

    @tool
    def get_media_insights(media_id: str, metrics: List[MediaInsightMetric], runtime: ToolRuntime[None, EngagementState]) -> str:
        "Fetch Instagram insights for one specific post. Which metrics are valid depends on the post's media type: FEED posts and REELS support 'likes'/'comments'/'reach'/'saved'/'shares'/'total_interactions', REELS add watch-time and skip-rate metrics, STORY supports 'navigation'/'link_clicks'/'replies'/'follows'. Not available for carousel/album items; story metrics expire 24h after posting. Instagram only — use get_threads_media_insights for Threads posts. Returns the raw metrics JSON."
        influencer_name = runtime.state.get("influencer_name")
        token, _ = _get_meta_credentials(influencer_name, "instagram")
        resp = httpx.get(f"https://graph.instagram.com/v25.0/{media_id}/insights",
                        params={"metric": ",".join(metrics), "access_token": token})
        if resp.is_error or "error" in resp.json():
            raise RuntimeError(f"Failed to fetch insights for {media_id}: {resp.text}")
        return json.dumps(resp.json().get("data", []))

    @tool
    def get_threads_media_insights(media_id: str, metrics: List[ThreadsMediaInsightMetric], runtime: ToolRuntime[None, EngagementState]) -> str:
        "Fetch insights for one specific Threads post: 'views' (times played/displayed), 'likes', 'replies' (total replies if this post is a root post, direct replies only if it's itself a reply), 'reposts', 'quotes', 'shares'. Note: metrics don't capture nested replies, and an empty list is returned for reposts of someone else's post. Threads only — use get_media_insights for Instagram. Returns the raw metrics JSON."
        influencer_name = runtime.state.get("influencer_name")
        token, _ = _get_meta_credentials(influencer_name, "threads")
        resp = httpx.get(f"https://graph.threads.com/v1.0/{media_id}/insights",
                        params={"metric": ",".join(metrics), "access_token": token})
        if resp.is_error or "error" in resp.json():
            raise RuntimeError(f"Failed to fetch insights for {media_id}: {resp.text}")
        return json.dumps(resp.json().get("data", []))
