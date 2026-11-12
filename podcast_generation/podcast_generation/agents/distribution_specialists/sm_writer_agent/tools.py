from podcast_generation.settings import DATA_DIR, SKILLS_DIR, require_env
from openrouter import OpenRouter, utils
import os, frontmatter, re
from pathlib import Path
from typing import List, Tuple
import base64, requests, dropbox
from typing import Literal
from dropbox.exceptions import ApiError

from langchain.tools import tool, ToolRuntime
from langgraph.types import Command
from langchain_core.messages import ToolMessage

from .state import SMWriterState


from functools import cache


@cache
def get_dropbox() -> dropbox.Dropbox:
    """Dropbox client, created on first use rather than at import."""
    return dropbox.Dropbox(oauth2_access_token=require_env("DROPBOX"))


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
            full_output_path = str(DATA_DIR / output_path)
            os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
            image_bytes = base64.b64decode(res.data[0].b64_json)
            with open(full_output_path, "wb") as f:
                f.write(image_bytes)

            dbx = get_dropbox()
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
    async def export_and_download_design(design_id: str, format: dict, output_path: str, runtime: ToolRuntime[None, SMWriterState]) -> str:
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
        full_path = str(DATA_DIR / output_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(response.content)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Design is successfully saved to {full_path}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "image_post_path": full_path,
            }
        )

    @tool
    def save_post_text(output_path: str, text: str, runtime: ToolRuntime[None, SMWriterState]):
        "Save the text content of the post. Use md format"
        full_path = str(DATA_DIR / output_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(text)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Post text successfully saved!",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
                "caption_path": full_path,
            }
        )

    @tool
    def create_folder(folder_path: str, folder_name: str):
        "Tool to create a folder to save content locally"
        path = os.makedirs(DATA_DIR / folder_path / folder_name, exist_ok=True)
        return path

    @tool
    def load_skill_content(skill_name: str) -> str:
        "Load the content of the specific skill"
        post = frontmatter.load(SKILLS_DIR / "distribution_skills" / "sm_writer_agent" / f"{skill_name}.md")
        return post.content

    @tool
    def load_available_skills() -> List[Tuple[str, str]] | str:
        "Load the name and descriptions of the available skills"
        os.makedirs(SKILLS_DIR / "distribution_skills" / "sm_writer_agent", exist_ok=True)
        all_skills = list(Path(SKILLS_DIR / "distribution_skills" / "sm_writer_agent").glob("*.md"))
        if all_skills:
            all_metadata = []
            for skill in all_skills:
                post = frontmatter.load(skill)
                all_metadata.append(post.metadata)
            return all_metadata
        else:
            return "No skills available yet!"
