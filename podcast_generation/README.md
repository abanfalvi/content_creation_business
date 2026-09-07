# Podcast Generation

A multi-agent pipeline that turns a book into a podcast episode: it picks a book, builds an
expert persona to interview, drafts a two-voice script, generates host/expert audio, mixes the
episode, and prepares social posts — with a human approval gate at each major step.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) / [LangChain](https://github.com/langchain-ai/langchain),
with per-agent models routed through [OpenRouter](https://openrouter.ai/) and traces sent to
[Opik](https://www.comet.com/site/products/opik/).

## Architecture

Three tiers, each with a **director** that routes to its **specialist agents** and holds shared
state across the run:

- **Content Director** — `Book Selection Agent` → `Expert Profile Builder` → `Script Drafter Agent`,
  then a human review gate before the script is final.
- **Production** — `speech_gen_workflow` generates host/expert audio (TTS) and hands it to the
  `Audio Engineer Agent` to assemble the episode, looping on revisions until approved.
- **Distribution Director** — `Social Media Writer Agent` → `Publisher Agent`, with an
  LLM-adjudicated review step (no human gate).

Each director is a LangGraph state machine whose `active_agent` step selects which specialist
runs next (see `--step` on the `content` and `distribution` CLI commands). Runs are checkpointed
per book/tier in SQLite (`checkpoints/`), so any workflow can be paused and resumed by thread ID.

Every specialist that completes successfully can have its trace converted into a versioned
**skill** (`podcast skills convert-traces`) — a written-down procedure that gets loaded back into
that agent's context on future runs via `FilesystemFileSearchMiddleware` over `src/skills/`.

## Project layout

```
src/
  agents/
    content_specialists/       book selection, expert builder, script drafter, director
    production_specialists/    TTS generation, audio engineer, director
    distribution_specialists/  social writer, publisher, director
    models.py                  which OpenRouter model each agent runs on
  cli/                         Typer CLI + interactive REPL
  memory/                      shared long-term store (lessons learned, successful traces)
  skills/                      generated skill files, one folder per agent
  vector_db.py                 PDF -> chunks -> embeddings pipeline for book ingestion
  book_list.json               book wishlist / candidates (gitignored, local only)
data/<book-slug>/              per-book working files: book content, expert persona, script, audio
checkpoints/                   LangGraph SQLite checkpoints (content / production / distribution)
podcast_books_db/              Chroma vector store for ingested books
assets/PROJECT.md              design notes: agent architecture, memory strategy, roadmap
```

## Setup

Requires Python 3.13+.

```bash
pip install -e .
```

This registers the `podcast` command (`src/cli/main.py:app`).

Copy `.env.example` to `.env` (create one if missing) and fill in the keys you need:

| Variable | Used for |
|---|---|
| `OPENROUTER_API_KEY` | LLM calls for every agent |
| `COHERE_API_KEY` | embeddings / reranking |
| `TAVILY_API_KEY` | book/web search |
| `MINERU_API_KEY` | PDF parsing during book preprocessing |
| `HF_TOKEN` | Hugging Face model/dataset access |
| `OPIK_API_KEY`, `OPIK_CONSOLE_LOGGING_LEVEL` | tracing via Opik |
| `LANGSMITH_TRACING`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT` | optional LangSmith tracing |
| `POSTGRES_URI` | optional Postgres checkpointer instead of SQLite |
| `BUFFER_API_KEY` | scheduling/publishing social posts |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_ACCESS_TOKEN` | podcast platform publishing |
| `DROPBOX` | asset storage |

## Usage

Run `podcast` with no arguments for the interactive REPL (book wishlist, guided prompts for
every command, `/status` to see active threads). Or drive it directly:

```bash
# Ingest a book from the wishlist into the vector DB
podcast books preprocess --book-genre "Marketing & Psychology" --book-name "Contagious: Why Things Catch On" --end-page 240

# Find/refine candidate books
podcast books search "books on consumer psychology and viral marketing"

# Drive the content pipeline one step at a time (defaults to the expert-builder step)
podcast content run "Draft the episode" --book-title "Contagious: Why Things Catch On" --step call_book_selection_agent

# Generate and review episode audio (loops until approved, applying --feedback on revisions)
podcast production run --book-title "Contagious: Why Things Catch On" --expert-name "Jonah Berger"

# Prepare social posts and publish
podcast distribution run --book-title "Contagious: Why Things Catch On"

# Turn a successful run's trace into a reusable skill
podcast skills convert-traces content_traces

# Delete checkpoint threads older than 30 days
podcast maintenance prune-checkpoints --db all
```

Each command accepts `--thread-id` to resume a specific run instead of the book's most recent
one; thread IDs are tracked per book/tier in `.podcast_cli/state.json`.
