from openrouter import OpenRouter, utils
from dotenv import load_dotenv
import os
import time
import base64, requests
from typing import Literal
from langchain.tools import tool, ToolRuntime
from langgraph.types import Command

from langchain_core.messages import HumanMessage, ToolMessage

from huggingface_hub import HfApi

load_dotenv()

hf_token = HfApi()
hf_token.create_repo(repo_id="abanfalvi/podcast-social-assets", repo_type="dataset", exist_ok=True)

_spotify_token_cache = {"access_token": None, "expires_at": 0}


def _get_spotify_token() -> str:
    "Fetch (and cache) an app-only Spotify access token via the Client Credentials flow."
    if _spotify_token_cache["access_token"] and time.time() < _spotify_token_cache["expires_at"]:
        return _spotify_token_cache["access_token"]

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.getenv("SPOTIFY_CLIENT_ID"),
            "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET"),
        },
        timeout=15,
    )
    response.raise_for_status()
    token_data = response.json()
    _spotify_token_cache["access_token"] = token_data["access_token"]
    _spotify_token_cache["expires_at"] = time.time() + token_data["expires_in"] - 60
    return _spotify_token_cache["access_token"]

class SMWriterAgentTools:

    @tool
    def generate_image(prompt: str, output_path: str, aspect_ratio: Literal["1:1", "1:2", "1:4", "2:1", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "9:16", "16:9"]) -> str:
        "Generates image based on the provided prompt, and not every aspect ratio is available for every model"
        with OpenRouter(api_key=os.getenv("OPENROUTER_API_KEY", "")) as open_router:
            res = open_router.images.generate(
                model="krea/krea-2-medium-turbo",
                prompt=prompt,
                n=1,
                aspect_ratio=aspect_ratio,
                output_format="jpeg",
                timeout_ms=60000,
                retries=utils.RetryConfig("backoff", utils.BackoffStrategy(500, 5000, 1.5, 30000), False),
            )
            image_bytes = base64.b64decode(res.data[0].b64_json)
            with open(output_path, "wb") as f:
                f.write(image_bytes)

            hf_token.upload_file(
                path_or_fileobj=output_path, 
                path_in_repo=os.path.basename(output_path),
                repo_id="abanfalvi/podcast-social-assets",
                repo_type="dataset",
            )
            public_url = f"https://huggingface.co/datasets/abanfalvi/podcast-social-assets/resolve/main/{os.path.basename(output_path)}"

        return public_url

    @tool
    def download_export(url: str, output_path: str) -> str:
        "Download an exported design from its temporary Canva URL and save it locally."
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path

    @tool
    def save_post_text(output_path: str, text: str):
        with open(output_path, "w") as f:
            f.write(text)
        return "Post text successfully saved!"

    @tool
    def create_folder(folder_path: str, folder_name: str):
        "Tool to create a folder to save content locally"
        path = os.mkdir(f"{folder_path}/{folder_name}")
        return path

class PublisherAgentTools:

    @tool
    def search_show(query: str, limit: int = 5) -> list[dict]:
        "Search Spotify for a podcast show by name. Returns candidate shows with their show_id, to be used as input to get_show_info or get_show_episodes."
        token = _get_spotify_token()
        response = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "show", "limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()["shows"]["items"]
        return [
            {
                "show_id": show["id"],
                "name": show["name"],
                "description": show["description"],
                "total_episodes": show["total_episodes"],
                "url": show["external_urls"]["spotify"],
            }
            for show in items
        ]

    @tool
    def search_episode(query: str, limit: int = 5) -> list[dict]:
        "Search Spotify for an episode by keyword. Returns candidate episodes with their episode_id, to be used as input to get_episode_details."
        token = _get_spotify_token()
        response = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "episode", "limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()["episodes"]["items"]
        return [
            {
                "episode_id": episode["id"],
                "name": episode["name"],
                "release_date": episode["release_date"],
                "url": episode["external_urls"]["spotify"],
            }
            for episode in items
        ]

    @tool
    def get_show_info(show_id: str) -> dict:
        "Get details for a Spotify show, including its cover art and episode count. Use search_show first to find the show_id."
        token = _get_spotify_token()
        response = requests.get(
            f"https://api.spotify.com/v1/shows/{show_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()
        show = response.json()
        return {
            "name": show["name"],
            "description": show["description"],
            "total_episodes": show["total_episodes"],
            "cover_image_url": show["images"][0]["url"] if show["images"] else None,
            "url": show["external_urls"]["spotify"],
        }

    @tool
    def get_show_episodes(show_id: str, limit: int = 10) -> list[dict]:
        "Fetch the most recent episodes for a Spotify show, including each episode's episode_id and public Spotify URL. Use search_show first to find the show_id."
        token = _get_spotify_token()
        response = requests.get(
            f"https://api.spotify.com/v1/shows/{show_id}/episodes",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit},
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()["items"]
        return [
            {
                "episode_id": episode["id"],
                "name": episode["name"],
                "release_date": episode["release_date"],
                "url": episode["external_urls"]["spotify"],
            }
            for episode in items
        ]

    @tool
    def get_episode_details(episode_id: str) -> dict:
        "Get full details for a specific Spotify episode. Use search_episode or get_show_episodes first to find the episode_id."
        token = _get_spotify_token()
        response = requests.get(
            f"https://api.spotify.com/v1/episodes/{episode_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        response.raise_for_status()
        episode = response.json()
        return {
            "name": episode["name"],
            "description": episode["description"],
            "duration_ms": episode["duration_ms"],
            "release_date": episode["release_date"],
            "cover_image_url": episode["images"][0]["url"] if episode["images"] else None,
            "url": episode["external_urls"]["spotify"],
        }
