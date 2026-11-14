from e2b import Template, default_build_logger

from podcast_generation.settings import E2B_TEMPLATE, require_env

PROJECT_DIR = "/home/user/remotion-project"
SKILLS_DIR = "/home/user/remotion-skills"

# Shared libraries Remotion's headless Chrome needs on Debian
# (https://www.remotion.dev/docs/miscellaneous/linux-dependencies).
CHROME_DEPS = [
    "libnss3", "libdbus-1-3", "libatk1.0-0", "libgbm-dev", "libasound2", "libxrandr2",
    "libxkbcommon-dev", "libxfixes3", "libxcomposite1", "libxdamage1", "libatk-bridge2.0-0",
    "libpango-1.0-0", "libcairo2", "libcups2",
]


def remotion_template():
    return (
        Template()
        .from_node_image("22-bookworm")
        .apt_install(CHROME_DEPS + ["ffmpeg"], no_install_recommends=True)
        .run_cmd("npx --yes create-video@latest --yes --blank remotion-project --no-skills")
        .git_clone("https://github.com/remotion-dev/skills", SKILLS_DIR, depth=1)
        .set_workdir(PROJECT_DIR)
        .run_cmd("rm -rf .git")
        .run_cmd("npx remotion add @remotion/media")
        .run_cmd("npx remotion browser ensure")
        # Smoke test: bundle the project and launch the browser. Fails the build if Chrome can't start.
        .run_cmd("npx remotion compositions src/index.ts")
    )


def build(name: str = E2B_TEMPLATE):
    require_env("E2B_API_KEY")
    return Template.build(
        remotion_template(),
        name,
        cpu_count=2,
        memory_mb=2048,  # headless Chrome needs more than the default 512 MB
        on_build_logs=default_build_logger(),
    )


if __name__ == "__main__":
    info = build()
    print(f"Built template {info.name!r} ({info.template_id})")
