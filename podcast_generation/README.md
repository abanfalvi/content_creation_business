# Podcast Generation

A multi-agent pipeline that turns a non-fiction book into a finished podcast episode. It ingests
the book, invents an expert persona to "interview", plans and writes a two-voice script, checks
that script against the book, synthesises and edits the audio, then writes the social post and
publishes. A human approves the script and the final audio; everything else runs on its own.

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

`podcast books preprocess` ([pipeline.py](src/book_preprocessing/pipeline.py)) takes a book from the
wishlist in `src/book_list.json` (which must have a `filepath` to the PDF) and produces everything
the agents read later:

| Step | What happens | Output |
|---|---|---|
| Parse | The PDF is sent to MinerU in 200-page batches and converted to Markdown | `data/<slug>/book_content.md` |
| Chunk | The table of contents is matched to headers to find chapter boundaries; the text is split into ~2k-character chunks | chunks tagged with `chapter` |
| Contextualise | An LLM writes a short summary of each chunk's neighbours, so an isolated chunk still says where it sits in the book | `context_summary` per chunk |
| Embed | Chunks are embedded and stored in Chroma, keyed by `book_slug` (re-ingesting a book replaces its chunks) | `podcast_books_db/` |
| Digest | A map/reduce pass over the whole book builds a line-cited map: thesis, structure, frameworks, examples, objections, verbatim author quotes. Quotes are verified against the text; the digest is skipped if the book file hasn't changed | `data/<slug>/book_digest.md` |

The *slug* is the book's identity everywhere: the title lowercased with spaces, colons and commas
turned into underscores (`get_book_path` in [utils.py](src/agents/content_specialists/utils.py)). It names the
`data/<slug>/` folder and filters vector search.

Agents reach the book in three ways: **`retrieve_info`** (semantic search: the top 75 chunks for the
book are reranked down to 6 and returned with their context summaries), **line-range reads** of
`book_content.md`, and **grep** over the `data/` folder.

### 2. Content: from book to approved script

The **Content Director** ([director/](src/agents/content_specialists/director/)) sequences the
specialists. Each of its tool calls sets `active_agent` in the state, and a middleware swaps in the
prompt and the *only* tools allowed for that step. So a run chains itself through the stages,
and `--step` on the CLI just chooses where to start.

```
select_books ─► build_expert_profile ─► review_expert_profile ─► draft_script ─► human_review
 (Book Selection)  (Expert Builder)      (director checks the     (Planner, then    │ approve ─► lessons
                         ▲                persona against a        Drafter)         │ reject  ─► feedback back to the
                         └─── fails the check ─┘                                    └────────────  director, which re-routes
```

- **Book Selection Agent** searches the web (Tavily) and maintains the wishlist in `src/book_list.json`
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
- **Revision loop** ([revision_loop.py](src/agents/content_specialists/script_drafter_agent/revision_loop.py)).
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

`speech_gen_workflow` ([speech_generation.py](src/agents/production_specialists/speech_generation.py))
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
- **Success traces become skills.** `podcast skills convert-traces content_traces` turns them into
  Markdown skill files under `src/skills/`. Specialists list and load these with `load_available_skills` /
  `load_skill_content`, and the director can search them.
- The directors can edit a specialist's `prompt.md` or rewrite a skill, but only when the user explicitly asks.

### State, threads and resuming

- Each tier checkpoints to its own SQLite file in `checkpoints/` (content, production, distribution).
- A run is a LangGraph *thread*. The director's thread is `<id>`, and each specialist gets a child thread
  such as `<id>::expert_builder`, `<id>::script_drafter`. The CLI remembers the latest thread per book and tier
  in `.podcast_cli/state.json`; pass `--thread-id` to resume a specific one.
- Human gates are LangGraph interrupts. The CLI shows the script or audio and asks you to approve or give feedback.
- Models are chosen per agent in [models.py](src/agents/models.py). Several agents have fallback models
  that take over if the primary one fails.

## Project layout

```
src/
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
  reranker.py                  rerank adapter used by retrieve_info
  memory/memory_store.py       shared Postgres store for lessons-learned traces
  skills/                      generated skill files, one folder per agent
  skill_converter.py           success traces -> skill files
  prune_checkpoints.py         deletes old checkpoint threads
  cli/                         Typer CLI and the interactive REPL
  book_list.json               book wishlist (gitignored, you create it)
data/                          per-book working files (gitignored)
checkpoints/  podcast_books_db/  .podcast_cli/   runtime state (gitignored)
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
| `book_digest.md` | ingestion (`books digest`) |
| `expert_persona.md` | Expert Profile Builder |
| `planner_notes.md` | Script Planner (working notes) |
| `script_plan.md` | Script Planner |
| `script.md` | Script Drafter |
| `audio_contents/` | TTS and Audio Engineer |

`data/host_persona.md` (the host, shared by every book) is a file you maintain by hand.

## Setup

Requires Python 3.13+, [ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) on your `PATH` (the
file-search tools and the script evaluators use it), and a reachable Postgres database.

```bash
pip install -e .
```

This registers the `podcast` command (`src/cli/main.py:app`). ffmpeg for audio editing comes from
`static_ffmpeg`.

Create `.env` with:

| Variable | Used for |
|---|---|
| `OPENROUTER_API_KEY` | every LLM, embedding, rerank, TTS and image call |
| `POSTGRES_URI` | **required**: the shared store for lessons-learned traces (read at import time) |
| `TAVILY_API_KEY` | web search in book selection |
| `MINERU_API_KEY` | PDF parsing during ingestion |
| `OPIK_API_KEY`, `OPIK_CONSOLE_LOGGING_LEVEL` | tracing (the Opik workspace and project are set in `models.py`) |
| `BUFFER_API_KEY` | publishing posts via Buffer |
| `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` | looking up the show and episodes on Spotify |
| `DROPBOX` | Dropbox access token for hosting post images |

Canva is authorised through an OAuth browser flow the first time the Social Media Writer needs it
(the token is cached in `.mcp_tokens.json`).

Create `src/book_list.json` (it's gitignored) with the books you want to work on. `filepath` is the
local PDF:

```json
{
  "list_of_books": {
    "wishlist": {
      "Marketing & Psychology": [
        {"title": "Contagious: Why Things Catch On", "author": "Jonah Berger", "abstract": "...", "filepath": "C:/books/contagious.pdf"}
      ]
    },
    "finished": {}
  }
}
```

The Book Selection Agent can also fill this in for you (`podcast books search ...`).

## Usage

Run `podcast` with no arguments for the interactive REPL (wishlist, guided prompts for every
command, `/status` to see active threads). Or drive each stage directly:

```bash
# 1. Ingest: parse, chunk, embed and digest a wishlist book
podcast books preprocess --book-genre "Marketing & Psychology" --book-name "Contagious: Why Things Catch On" --end-page 240

# (Re)build only the digest of an already ingested book
podcast books digest --book-title "Contagious: Why Things Catch On"

# Find or refine candidate books
podcast books search "books on consumer psychology and viral marketing"

# 2. Content: expert -> plan -> script -> evaluators -> your approval
podcast content run "Build the expert and draft the episode" --book-title "Contagious: Why Things Catch On"
#    --step picks the starting stage (default: call_expert_builder_agent); the run chains on from there.
#    Others: call_book_selection_agent, call_script_drafter_agent, review_expert_profile,
#    edit_prompts_skills, get_lessons_learned, full_flexibility.

# 3. Production: TTS, audio engineering, your approval (loops on --feedback)
podcast production run --book-title "Contagious: Why Things Catch On" --expert-name "Jonah Berger"

# 4. Distribution: social post and publishing
podcast distribution run --book-title "Contagious: Why Things Catch On"

# Turn saved successful traces into skills (content_traces | production_traces | distribution_traces)
podcast skills convert-traces content_traces

# Delete checkpoint threads older than 30 days
podcast maintenance prune-checkpoints --db all
```

`--expert-name` must match the speaker label used in the script, and the host is always "Jordan"
(the TTS voice map in `speech_generation.py` is keyed on those names).

Every command accepts `--thread-id` to resume a specific run instead of the book's most recent one.
