# Podcast Generation

A multi-agent pipeline that turns a non-fiction book into a finished podcast episode, wrapped in a web app
(**Level Up Lab**). You add PDF books; the app ingests them, lets you chat with the ones you select, and
generates episodes: it invents an expert persona to "interview", plans and writes a two-voice script, checks
that script against the book, synthesises and edits the audio, then writes the social post and
publishes. A human approves the script and the final audio; everything else runs on its own.

- **Sources** (left): add PDFs (upload or drag and drop). They are processed automatically; tick the ones you want to work with.
- **Chat** (middle): ask questions about the ticked sources, with the supporting passages shown. Start as many chats as you like.
- **Studio** (right): *Generate podcast* for one source (you approve the script, then the audio) and *Publish* a generated episode.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) / [LangChain](https://github.com/langchain-ai/langchain).
Every model call is routed through [OpenRouter](https://openrouter.ai/) and traced in
[Opik](https://www.comet.com/site/products/opik/).

## How it works

```
 PDF ──► INGEST ──► CONTENT ──────────────────────────► PRODUCTION ──► DISTRIBUTION
         parse       Book Selection                      TTS per turn    Social Media Writer
         chunk       Expert Profile Builder              Audio Engineer  review (LLM)
         embed       Script Planner  ─► plan w/ citations  rubric score   Publisher
         digest      Script Drafter  ◄─ 3 evaluators       │
                          │                               human gate
                     human gate (approve script)          (approve audio)
                          │                                    │
                          └──────── approved runs become lessons ──► skills ──┐
                                          ▲                                    │
                                          └────── loaded into agents' next runs┘
```

Three ideas run through the whole design:

1. **The book is the only source of truth.** Every claim in the script has to trace back to a line
   of the book. The planner cites line numbers, the drafter only writes what the plan supports, and
   independent evaluators check the result against the book.
2. **Directors route, specialists work.** Each stage has a *director* agent that does no
   creative work itself. It decides which *specialist* runs next and passes feedback along.
3. **Runs improve the next run.** Approved runs are mined for lessons, which are fed back to the
   specialists as warnings, and (optionally) converted into reusable skill files.

### 1. Ingest a book

Adding a PDF in the web app runs `preprocess_book` ([pipeline.py](podcast_generation/book_preprocessing/pipeline.py)),
one book at a time in the background, and produces everything the agents (and the chat) read later. The book's title
comes from the file name.

| Step | What happens | Output |
|---|---|---|
| Parse | The PDF is sent to MinerU in 200-page batches and converted to Markdown | `data/<slug>/book_content.md` |
| Chunk | The table of contents is matched to headers to find chapter boundaries; the text is split into ~2k-character chunks | chunks tagged with `chapter` |
| Contextualise | An LLM writes a short summary of each chunk's neighbours, so an isolated chunk still says where it sits in the book | `context_summary` per chunk |
| Embed | Chunks are embedded and stored in Chroma, keyed by `book_slug` (re-ingesting a book replaces its chunks) | `podcast_books_db/` |
| Digest | A map/reduce pass over the whole book builds a line-cited map: thesis, structure, frameworks, examples, objections, verbatim author quotes. Quotes are verified against the text; the digest is skipped if the book file hasn't changed | `data/<slug>/book_digest.md` |

The *slug* is the book's identity everywhere: the title lowercased with spaces, colons and commas
turned into underscores (`get_book_path` in [utils.py](podcast_generation/agents/content_specialists/utils.py)). It names the
`data/<slug>/` folder and filters vector search.

Agents reach the book in three ways: **`retrieve_info`** (semantic search: the top 75 chunks for the
book are reranked down to 6 and returned with their context summaries), **line-range reads** of
`book_content.md`, and **grep** over the `data/` folder.

### 2. Content: from book to approved script

The **Content Director** ([director/](podcast_generation/agents/content_specialists/director/)) sequences the
specialists. Each of its tool calls sets `active_agent` in the state, and a middleware swaps in the
prompt and the *only* tools allowed for that step. So a run chains itself through the stages from the first step.

```
select_books ─► build_expert_profile ─► review_expert_profile ─► draft_script ─► human_review
 (Book Selection)  (Expert Builder)      (director checks the     (Planner, then    │ approve ─► lessons
                         ▲                persona against a        Drafter)         │ reject  ─► feedback back to the
                         └─── fails the check ─┘                                    └────────────  director, which re-routes
```

- **Book Selection Agent** searches the web (Tavily) and maintains the wishlist in `podcast_generation/book_list.json`
  (wishlist → finished).
- **Expert Profile Builder** reads the book digest first, then retrieves and reads further passages,
  and writes `expert_persona.md`: a *fictional* expert (Identity, Core arguments, Voice, Signature
  material, Likely pushback), grounded in the book. The director then reviews the persona against an
  explicit checklist (clearly fictional, every claim traceable to the book, all five sections, consistent,
  enough material to write dialogue) and either sends it back with specific criticism or moves on.
- **Script Planner** does *all* of the book research. It reads the whole book in windows, keeps working
  notes, and writes `script_plan.md`: thesis, cold-open candidates, setup, four to six main segments
  (one idea each, with self-contained evidence), a counterargument ("the turn"), a practical close and outro takeaways.
  **Every piece of evidence ends with a line citation** like `[L120-135]`. An automated check
  (an LLM judge via OpenRouter's decisions endpoint) scores whether the plan is finished, complete and cited,
  and sends the planner back for up to three attempts. The planner runs only when no plan exists, or when the
  director asks for `replan=true` (after a persona change, or feedback that the episode covers the wrong ideas).
- **Script Drafter** turns the plan plus the host persona (`data/host_persona.md`, shared by every episode)
  and the expert persona into `script.md`, built up segment by segment. The script is plain
  `**Speaker:** line` turns because the audio stage parses it directly. It is not supposed to research:
  `retrieve_info` is only a fallback for confirming or filling a thin spot in the plan.
- **Revision loop** ([revision_loop.py](podcast_generation/agents/content_specialists/script_drafter_agent/revision_loop.py)).
  When the drafter finishes, three evaluators run in parallel against the script and the book:
  *fidelity* (does the script match the book?), *structure* (alternating turns, pacing, no repeats) and
  *depth* (does it reach second examples and mechanisms?). Each returns a 0–1 score and findings that quote
  the exact spot to fix. If the average is at least 0.8 the script passes. Otherwise an integrator merges the
  findings (fidelity > structure > depth) into one set of instructions and sends them back to the drafter,
  for at most two rounds.
- **Human review.** The run then pauses with the script on screen. Approve it, or reject it with feedback.
  The director reads the feedback and decides where the problem lives: the persona (rebuild it, then
  replan), the plan (replan), or the prose (redraft from the existing plan).

**Context compaction.** The Expert Builder and Script Drafter each have a `compact_context_window` tool. When
their context grows long they call it, and a cheap model replaces the whole history with a structured memory
entry (what's been read or written, confirmed facts with line citations, ruled-out paths, open feedback, next
steps). The agent chooses when to do it, rather than a middleware trimming at a fixed token count.

### 3. Production: from script to audio

`speech_gen_workflow` ([speech_generation.py](podcast_generation/agents/production_specialists/speech_generation.py))
is a plain LangGraph graph rather than a director:

1. **Generate**: each `**Speaker:**` turn is voiced with an OpenRouter TTS model (one voice for the host
   "Jordan", one for the expert), joined with short pauses, and saved to `data/<slug>/audio_contents/`.
2. **Audio Engineer Agent**: a multimodal model *listens* to the episode and fixes it with editing tools
   (volume, fades, trims, silence removal, overlays, regenerating a line), then scores it on a 1–5 rubric:
   loudness consistency, noise and clarity, silence and pacing, transitions, technical compliance.
3. **Human review**: the run pauses with the audio path and rubric. Approve, or send feedback back to the
   Audio Engineer. This loops until approved.
4. **Lessons learned**: on approval, an extractor agent distils the engineer's trace into lessons.

### 4. Distribution: from audio to published post

The **Distribution Director** runs fully automatically (no human gate):

1. **Social Media Writer** reads the script, generates an image (OpenRouter image model), stores it in Dropbox
   and Canva, and writes the caption.
2. **Review** (an LLM step): the director looks at the caption and image together and decides to
   accept, or send either back to be redone.
3. **Publisher** looks up the show on Spotify and schedules the post through the Buffer MCP server.
4. Lessons learned are saved as in the other tiers.

### 5. How the system learns

- On approval, the director runs a `get_lessons_learned` step. It reads the checkpointed traces of the
  director and each specialist and saves **book-agnostic** success and failure traces to a shared store (Postgres).
- **Failure traces are fed back automatically.** Before a specialist is called, the director appends the stored
  "avoid / prefer" lessons for that agent to its instructions.
- **Success traces become skills.** `convert_to_skill("content_traces")` in `skill_converter.py` turns them into
  Markdown skill files under `podcast_generation/skills/`. Specialists list and load these with `load_available_skills` /
  `load_skill_content`, and the director can search them.
- The directors can edit a specialist's `prompt.md` or rewrite a skill, but only when the user explicitly asks.

### State, jobs and resuming

- Each tier checkpoints to its own SQLite file in `checkpoints/` (content, production, distribution, chat).
- The web app's own records (sources, chat list, jobs, episodes) are in `app.db`.
- Generating an episode is a *job*. Its id is the LangGraph thread id of the director, and each specialist gets a
  child thread such as `<id>::expert_builder`. A job runs content, then production, pausing at each human gate.
- Human gates are LangGraph interrupts. The Studio panel shows the script or audio and sends your decision back,
  which resumes the graph. A job waiting for your approval survives a server restart; one that was mid-run does not
  (it is marked failed and can be started again). Each new run starts from a fresh persona, plan and script; the
  previous ones are moved to `data/<slug>/archive/`.
- Models are chosen per agent in [models.py](podcast_generation/agents/models.py). Several agents have fallback models
  that take over if the primary one fails.

## Project layout

```
podcast_generation/
  agents/
    models.py                  which OpenRouter model each agent uses, plus Opik tracing setup
    content_specialists/
      director/                routes between the specialists (step config, review/lesson steps)
      book_selection_agent/
      expert_builder_agent/
      script_planner_agent/    writes the cited plan; verified by an LLM judge
      script_drafter_agent/    writes the script; revision_loop.py + evaluator_prompts/ check it
      shared_tools.py          retrieve_info (vector search + rerank)
      compaction.py            the compact_context_window mechanism
      utils.py                 SQLite checkpointer, get_book_path (the slug)
    production_specialists/    speech_generation.py (TTS graph), audio engineer, lessons-learned extractor
    distribution_specialists/  director, social media writer, publisher, MCP clients (Canva, Buffer)
  book_preprocessing/          pdf_parsing, toc, chunking, context, embeddings, store (Chroma), digest, pipeline
  settings.py                  where everything lives on disk (data/, checkpoints/, skills/...) and .env loading
  media.py                     lazy ffmpeg / pydub setup
  reranker.py                  rerank adapter used by retrieve_info
  memory/memory_store.py       shared Postgres store for lessons-learned traces (connects on first use)
  skills/                      generated skill files, one folder per agent
  skill_converter.py           success traces -> skill files
  prune_checkpoints.py         deletes old checkpoint threads
  services/                    the app's logic: sources, chat, generation + publishing, app database
  api/                         FastAPI routes (/api/...) and the app that also serves the built frontend
  book_list.json               wishlist used by the Book Selection agent (gitignored)
frontend/                      React + TypeScript UI (Vite); `npm run build` writes frontend/dist
tests/                         API and workflow tests (stubbed models, no network)
data/                          per-book working files (gitignored)
uploads/  app.db  checkpoints/  podcast_books_db/   runtime state (gitignored)
```

Every agent folder follows the same pattern, with everything specific to the agent beside it:

```
<agent>/
  agent.py          builds the agent (model, middleware, tools) and exports it
  prompt.md         system prompt (directors can edit these at runtime)
  tools.py          its tools
  state.py          its LangGraph state schema
  step_prompts.py   directors only: per-step prompts
```

### What ends up in `data/<slug>/`

| File | Written by |
|---|---|
| `book_content.md` | ingestion |
| `book_digest.md` | ingestion |
| `expert_persona.md` | Expert Profile Builder |
| `planner_notes.md` | Script Planner (working notes) |
| `script_plan.md` | Script Planner |
| `script.md` | Script Drafter |
| `audio_contents/` | TTS and Audio Engineer |
| `episodes/` | approved episodes (audio + script), one pair per generated episode |
| `archive/` | the previous run's persona, plan and script |

`data/host_persona.md` (the host, shared by every book) is a file you maintain by hand.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (it fetches Python 3.13 if you don't have it), [Node.js](https://nodejs.org/) 20+
(only to build the frontend), [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) on your `PATH` (the file-search
tools and the script evaluators use it), and a reachable Postgres database.

```bash
uv sync                                   # creates .venv from uv.lock and installs the project (editable)
cd frontend && npm install && npm run build   # builds the UI into frontend/dist
```

For a local Postgres, `docker compose up -d postgres` starts one from [docker-compose.yml](docker-compose.yml) (data
persists in a Docker volume; `docker compose down -v` deletes it). Point `POSTGRES_URI` at it:
`postgresql://podcast:podcast@localhost:5432/podcast`.

ffmpeg for audio editing comes from `static_ffmpeg` (downloaded on first use). Dependencies live in `pyproject.toml`
(pinned) and `uv.lock`; change them with `uv add` / `uv remove` rather than editing the venv by hand, because
`uv sync` removes anything not declared.

Create `.env` in the project root (the folder containing `pyproject.toml`) with the variables below. It is found
from the package location, so the app works from any directory. Set `PODCAST_HOME` in the real environment to use a
different root for `.env`, `data/` and the other runtime folders.

| Variable | Used for |
|---|---|
| `OPENROUTER_API_KEY` | every LLM, embedding, rerank, TTS and image call |
| `POSTGRES_URI` | **required** for anything that runs a director or the production workflow: the shared store for lessons-learned traces (opened on first use, not at import) |
| `TAVILY_API_KEY` | web search in book selection |
| `MINERU_API_KEY` | PDF parsing during ingestion |
| `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_CONSOLE_LOGGING_LEVEL` | tracing (Opik is configured from the environment; the project name `podcast_generation` is set in `settings.py`) |
| `BUFFER_API_KEY` | publishing posts via Buffer |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | looking up the show and episodes on Spotify |
| `DROPBOX` | Dropbox access token for hosting post images |

Canva is authorised through an OAuth browser flow the first time publishing needs it (the token is cached in
`.mcp_tokens.json`). The server also reads `PODCAST_HOST` / `PODCAST_PORT` (default `127.0.0.1:8000`).

## Usage

```bash
uv run podcast-server        # then open http://127.0.0.1:8000
```

1. **Add sources.** Click *Add sources*, drop one or more PDFs, and wait for each to finish processing (a progress
   label shows on the row). New sources are ticked automatically; untick any you don't want to discuss.
2. **Chat.** Ask questions in the middle panel. Answers use only the ticked sources and show the passages they came
   from. *New chat* starts another conversation; the chat menu switches between them.
3. **Generate a podcast.** Tick exactly one source and choose *Generate podcast*. The Studio panel shows progress and
   opens a review dialog when the script is ready: approve it, or request changes with feedback and the director will
   rework it. After approval the audio is produced and edited, and you review that the same way.
4. **Publish.** Choose *Publish*, pick a generated episode and publish it: a social post is written and scheduled.

For development, run the API (`uv run podcast-server`) and the UI dev server (`cd frontend && npm run dev`, with
hot reload at http://localhost:5173, proxying `/api` to the API) side by side. Run the tests with `uv run pytest`.

The host is always called "Jordan" in scripts (the TTS voice map in `speech_generation.py` is keyed on that name);
the expert's name is read from the script.
