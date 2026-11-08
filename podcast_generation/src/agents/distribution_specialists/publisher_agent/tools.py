from dotenv import load_dotenv
import os, frontmatter, time
from pathlib import Path
from typing import List, Tuple
import requests

from langchain.tools import tool

load_dotenv()

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

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"skills/distribution_skills/publisher_agent/{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[Tuple[str, str]] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs("src/skills/distribution_skills/publisher_agent", exist_ok=True)
        all_skills = list(Path("src/skills/distribution_skills/publisher_agent/").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"
