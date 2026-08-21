from openrouter import OpenRouter, utils
from dotenv import load_dotenv
import os, frontmatter, time, re
from pathlib import Path
from typing import List, Tuple
import base64, requests, dropbox
from typing import Literal
from dropbox.exceptions import ApiError

from langchain.tools import tool, ToolRuntime


from huggingface_hub import HfApi

load_dotenv()

hf_token = HfApi()
hf_token.create_repo(repo_id="abanfalvi/podcast-social-assets", repo_type="dataset", exist_ok=True)

_spotify_token_cache = {"access_token": None, "expires_at": 0}

dbx = dropbox.Dropbox(oauth2_access_token=os.environ.get("DROPBOX"))

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
    async def generate_image_and_upload_canva(prompt: str, output_path: str, filename: str, aspect_ratio: Literal["1:1", "1:2", "1:4", "2:1", "2:3", "3:2", "3:4", "4:1", "4:3", "4:5", "5:4", "9:16", "16:9"], runtime: ToolRuntime) -> dict:
        "Generates an image from the prompt and uploads it into Canva as an asset, ready to place in a design. Not every aspect ratio is available for every model. Filename should be without file type."
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
            full_output_path = f"data/{output_path}"
            os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
            image_bytes = base64.b64decode(res.data[0].b64_json)
            with open(full_output_path, "wb") as f:
                f.write(image_bytes)

            dbx.files_upload(image_bytes, f"/{filename}.png")
            try:
                shared_link = dbx.sharing_create_shared_link_with_settings(f"/{filename}.png")
                url = shared_link.url
            except ApiError as e:
                if e.error.is_shared_link_already_exists():
                    existing = dbx.sharing_list_shared_links(path=f"/{filename}.png", direct_only=True).links
                    url = existing[0].url
                else:
                    raise

            direct_url = url.replace("?dl=0", "?raw=1")
            # resolve/main redirects (302) to a signed CDN URL — Canva's fetcher
            # checks for a 200 and won't follow redirects, so resolve it here.
            # public_url = requests.head(hf_url, allow_redirects=True, timeout=15).url

        upload_asset = next(t for t in runtime.tools if t.name == "upload-asset-from-url")
        # print(public_url)
        # time.sleep(25)
        try:
            return await upload_asset.ainvoke({
                "url": direct_url,
                "name": os.path.basename(output_path),
                "user_intent": "Upload a generated promotional image for the podcast's Instagram post into Canva.",
            })
        except:
            return f"Upload to Canva has been unsuccessful, but the image has been generated and saved to {full_output_path}"

    @tool
    def get_script(runtime: ToolRuntime):
        "Get the script for the episode to become familiar with content"
        return runtime.state.get("script")

    @tool
    async def export_and_download_design(design_id: str, format: dict, output_path: str, runtime: ToolRuntime) -> str:
        "Exports a Canva design and saves it locally in one step — no need to call export-design yourself or handle its temporary download URL. Call get-export-formats first to confirm a format this design actually supports."
        export_design = next(t for t in runtime.tools if t.name == "export-design")
        result = await export_design.ainvoke({
            "design_id": design_id,
            "format": format,
            "user_intent": "Export the finished Instagram post design so it can be saved locally for human review.",
        })

        urls = re.findall(r"https?://\S+", str(result))
        if not urls:
            raise ValueError(f"export-design did not return a download URL: {result}")

        response = requests.get(urls[0], timeout=30)
        response.raise_for_status()
        full_path = f"data/{output_path}"
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(response.content)
        return output_path

    @tool
    def save_post_text(output_path: str, text: str):
        "Save the text content of the post. Use md format"
        full_path = f"data/{output_path}"
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(text)
        return "Post text successfully saved!"

    @tool
    def create_folder(folder_path: str, folder_name: str):
        "Tool to create a folder to save content locally"
        path = os.makedirs(f"data/{folder_path}/{folder_name}", exist_ok=True)
        return path

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(f"skills/distribution_skills/sm_writer_agent/{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[Tuple[str, str]] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs("src/skills/distribution_skills/sm_writer_agent", exist_ok=True)
        all_skills = list(Path("src/skills/distribution_skills/sm_writer_agent/").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"

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
