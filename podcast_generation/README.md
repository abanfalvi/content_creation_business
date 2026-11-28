# Podcast Generation

A multi-agent pipeline that turns a source (a PDF or a YouTube video) into a finished podcast episode, wrapped in a web app
(**Level Up Lab**). You add sources; the app ingests them, lets you chat with the ones you select, and
generates episodes: it invents an expert persona to "interview", plans and writes a two-voice script, checks
that script against the source, then synthesises and edits the audio. A human approves the script and the final audio; everything else runs on its own.

- **Sources** (left): add PDFs (upload or drag and drop) or YouTube videos (paste a link). They are processed automatically; tick the ones you want to work with.
- **Chat** (middle): ask questions about the ticked sources, with the supporting passages shown. Start as many chats as you like.
- **Studio** (right): *Generate podcast* for the ticked sources (you approve the script, then the audio). Tick one source for an
  episode about it, or several for **one combined episode** that draws on all of them.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) / [LangChain](https://github.com/langchain-ai/langchain).
Every model call is routed through [OpenRouter](https://openrouter.ai/) and traced in
[Opik](https://www.comet.com/site/products/opik/).

## How it works

```
 PDF ──► INGEST ──► CONTENT ──────────────────────────► PRODUCTION
         parse                                          TTS per turn
         chunk       Expert Profile Builder              Audio Engineer
         embed       Script Planner  ─► plan w/ citations  rubric score
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

The *slug* is the book's identity everywhere: the title lowercased with spaces, colons and commas
turned into underscores (`get_book_path` in [utils.py](podcast_generation/agents/content_specialists/utils.py)). It names the
`data/<slug>/` folder and filters vector search.

### Adding a YouTube video

Pasting a video link in *Add sources* runs `preprocess_video` (same [pipeline.py](podcast_generation/book_preprocessing/pipeline.py),
code in [video.py](podcast_generation/book_preprocessing/video.py)). The video's title is its title, its channel is its author.

| Step | What happens | Output |
|---|---|---|
| Download | `yt-dlp` fetches the audio; ffmpeg turns it into mono 16 kHz mp3 (~48 kbps) | temporary |
| Split | The audio is cut into parts of about 5 minutes, at pauses found with ffmpeg's `silencedetect`, because the provider times out after about a minute per request | temporary |
| Transcribe | The parts are sent to `x-ai/grok-stt-2.0` on OpenRouter, four at a time, and joined into paragraphs of ~90 words; each part opens with its start time (`[05:00]`), so line numbers and timestamps both work for citations | `data/<slug>/book_content.md` |
| Decide | **Over 50,000 words**: chunked, contextualised and embedded exactly like a book. **50,000 words or fewer**: not chunked or embedded; the model reads the whole file | `data/<slug>/source.json` (`indexed`) |

A short (unindexed) video changes what the agents do, because there is nothing to search:

- **Chat** gets a `read_full_source` tool. The search tools skip such sources and say to read them whole; the passages it returns are
  paragraphs with their time stamps, so answers cite them like any other passage.
- **No digest** is built when an episode is generated; the Expert Builder's `read_book_digest` returns the whole transcript with line
  numbers instead, the Planner reads the file as it does for a book, and `retrieve_info` says that the source has no index rather than
  returning nothing (which would read as "the book never says this").

Requirements: `OPENROUTER_API_KEY`, and Node.js or Deno on the PATH (YouTube needs a JavaScript runtime for `yt-dlp`). Videos longer than 8 hours,
live streams, playlists and channel links are refused. The transcript is kept if a later step fails, and reused when the same video is added again.

Agents reach the book in three ways: **`retrieve_info`** (semantic search: the top 75 chunks for the
book are reranked down to 6 and returned with their context summaries), **line-range reads** of
`book_content.md`, and **grep** over the `data/` folder.

### 2. Content: from book to approved script

**Several sources, one episode.** When more than one source is ticked, `prepare_combined_source`
([combined.py](podcast_generation/book_preprocessing/combined.py)) joins them into one virtual source with its own
`data/<slug>/` folder: `book_content.md` holds every source's text under `=== SOURCE i of N: Title ===` banners, behind an
index of which lines belong to which source, and `source.json` lists the members. Everything downstream is keyed on the
slug, so line numbers, the digest, grep, the plan's citations, the persona, the script and the audio work unchanged;
`retrieve_info` searches every member's chunks and labels each passage with its source, and the prompts tell the agents
to keep each claim attributed to its own source. The job stores the member slugs and the combined title in `result`.

Before the director starts, a new generation job builds the **book digest** (`digest_book` in
[digest.py](podcast_generation/book_preprocessing/digest.py)), because only the expert builder and the planner read it, so
ingestion and chat don't pay for it. A map/reduce pass over the whole book builds a line-cited map: thesis,
structure, frameworks, examples, objections, verbatim author quotes. Quotes are verified against the text, and the
digest is skipped if the book file hasn't changed since the last one. Output: `data/<slug>/book_digest.md`.

The **Content Director** ([director/](podcast_generation/agents/content_specialists/director/)) sequences the
specialists. Each of its tool calls sets `active_agent` in the state, and a middleware swaps in the
prompt and the *only* tools allowed for that step. So a run chains itself through the stages from the first step.

```
build_expert_profile ─► review_expert_profile ─► draft_script ─► human_review
 (Expert Builder)      (director checks the     (Planner, then    │ approve ─► done
                        persona against a        Drafter)         │ reject  ─► feedback back to the
                        fails the check ─┘                          └────────────  director, which re-routes
```

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
4. **Lessons learned** (currently unhooked): the extractor agent that distils the engineer's trace into lessons is not
   run. After approval the workflow only cleans up the sandbox and ends.

### 4. How the system learns (currently unhooked)

> Memory and self-evolution are switched off for now. The code is all still there, but no Postgres store is passed to the
> directors or the production workflow, so nothing is saved, read back or edited. The directors no longer get the
> prompt-editing, skill-editing or trace-saving tools, and after an approval they just end. To hook it back in, pass
> `store=get_shared_store()` again (search for `UNHOOKED` in `podcast_generation/`), re-register the director tools,
> and send approvals to `get_lessons_learned` again. The rest of this section describes the hooked-in behaviour.

- On approval, the director runs a `get_lessons_learned` step. It reads the checkpointed traces of the
  director and each specialist and saves **book-agnostic** success and failure traces to a shared store (Postgres).
- **Failure traces are fed back automatically.** Before a specialist is called, the director appends the stored
  "avoid / prefer" lessons for that agent to its instructions.
- **Success traces become skills.** `convert_to_skill("content_traces")` in `skill_converter.py` turns them into
  Markdown skill files under `podcast_generation/skills/`. Specialists list and load these with `load_available_skills` /
  `load_skill_content`, and the director can search them.
- The directors can edit a specialist's `prompt.md` or rewrite a skill, but only when the user explicitly asks.

### State, jobs and resuming

- Each tier checkpoints to its own SQLite file in `checkpoints/` (content, production, chat).
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
      expert_builder_agent/
      script_planner_agent/    writes the cited plan; verified by an LLM judge
      script_drafter_agent/    writes the script; revision_loop.py + evaluator_prompts/ check it
      shared_tools.py          retrieve_info (vector search + rerank)
      compaction.py            the compact_context_window mechanism
      utils.py                 SQLite checkpointer, get_book_path (the slug)
    production_specialists/    speech_generation.py (TTS graph), audio engineer, lessons-learned extractor
  book_preprocessing/          pdf_parsing, video (yt-dlp + speech-to-text), source_meta, toc, chunking, context, embeddings, store (Chroma), digest, pipeline
  settings.py                  where everything lives on disk (data/, checkpoints/, skills/...) and .env loading
  media.py                     lazy ffmpeg / pydub setup
  reranker.py                  rerank adapter used by retrieve_info
  memory/memory_store.py       shared Postgres store for lessons-learned traces (connects on first use)
  skills/                      generated skill files, one folder per agent
  skill_converter.py           success traces -> skill files
  prune_checkpoints.py         deletes old checkpoint threads
  services/                    the app's logic: sources, chat, episode generation, app database
  api/                         FastAPI routes (/api/...) and the app that also serves the built frontend
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
| `book_digest.md` | the start of a generation job (not for a short video transcript) |
| `source.json` | ingestion: what kind of source it is and whether it is indexed |
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

ffmpeg for audio editing comes from `static_ffmpeg` (downloaded on first use). Dependencies live in `pyproject.toml`
(pinned) and `uv.lock`; change them with `uv add` / `uv remove` rather than editing the venv by hand, because
`uv sync` removes anything not declared.

Create `.env` in the project root (the folder containing `pyproject.toml`) with the variables below. It is found
from the package location, so the app works from any directory. Set `PODCAST_HOME` in the real environment to use a
different root for `.env`, `data/` and the other runtime folders.

| Variable | Used for |
|---|---|
| `OPENROUTER_API_KEY` | every LLM, embedding, rerank, TTS and image call |
| `POSTGRES_URI` | only needed if the lessons-learned store is hooked back in (see "How the system learns"); nothing reads it while that is off |
| `MINERU_API_KEY` | PDF parsing during ingestion |
| `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_CONSOLE_LOGGING_LEVEL` | tracing (Opik is configured from the environment; the project name `podcast_generation` is set in `settings.py`) |

The server also reads `PODCAST_HOST` / `PODCAST_PORT` (default `127.0.0.1:8000`).

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

For development, run the API (`uv run podcast-server`) and the UI dev server (`cd frontend && npm run dev`, with
hot reload at http://localhost:5173, proxying `/api` to the API) side by side. Run the tests with `uv run pytest`.

The host is always called "Jordan" in scripts (the TTS voice map in `speech_generation.py` is keyed on that name);
the expert's name is read from the script.
