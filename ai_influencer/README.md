# AI Influencer Agency

A multi-agent system that designs, launches and runs the content operation for AI-generated influencer
personas. Each influencer has a fixed character, personality, backstory and voice, and every post has
to stay consistent with them. You talk to one conversational **Orchestrator**, and it hands the work to
departments of specialist agents.

Built on [LangGraph](https://github.com/langchain-ai/langgraph) / [LangChain](https://github.com/langchain-ai/langchain).
Models are served through [OpenRouter](https://openrouter.ai/) and traced in
[Opik](https://www.comet.com/site/products/opik/).

> **Status: under active development.** This describes how the system is designed to work today.
> Prompts, agent boundaries and guardrails are still changing, and the Monetization department is
> planned but not wired up.

## How it works

```
                    ┌────────────────┐
      you  ───────► │  Orchestrator  │  routes, never does the work itself
                    └───────┬────────┘
        ┌───────────────────┼─────────────────────────┐
        ▼                   ▼                         ▼
 Persona & Identity   Content Production    Engagement & Community
 (workflow graph)     (manager + 2 agents)   (insights agent)
 ├─ Character Design  ├─ Content Strategist   ▲
 ├─ Personality       └─ SM Content Writer    │ Meta webhook (comments, mentions)
 ├─ Backstory              │                  │ runs without the orchestrator
 └─ human review           └─► Buffer         │
                                              │
        every run ──► Auditor ──► lessons ──► skills ──► loaded into the specialists' next runs
```

Four ideas run through the design:

1. **The persona files are the source of truth.** `CHARACTER.md`, `PERSONALITY.md` and `BACKSTORY.md`
   are written once, with a human approving them. Every later agent reads them, and the content
   guardrails check generated images and captions against them.
2. **Managers route, specialists work.** The orchestrator and the department managers don't create
   anything. They decide who acts next, hand over a concrete instruction, and report back what the
   specialist actually did. Each manager's tools are restricted by step, so an agent can only call what
   the current phase allows.
3. **Humans approve identity, machines police the output.** A person signs off on a new persona.
   Individual posts are not reviewed by a person. Automated reviewers check them before anything is published.
4. **Runs improve the next run.** An auditor mines each run's traces for lessons, and successful ones
   become skill files that the specialists load later.

### The Orchestrator

The orchestrator is the only agent the user talks to. It routes each request to one department:

- creating a new influencer goes to **Persona & Identity**
- planning, writing or posting content goes to **Content Production**
- "how are the posts doing?" goes to **Engagement & Community**

Its state holds **one active influencer** at a time. Content and engagement requests are refused until
one exists, and starting a new persona replaces the active one, so it asks before overwriting. It can
also read the persona files directly to answer questions about who the influencer is. It relays the
persona draft to the user in full during review and passes the user's verdict back. It does not
approve anything itself or invent feedback.

### Persona & Identity: creating an influencer

A LangGraph workflow ([persona_workflow.py](src/agents/persona_identity/persona_workflow.py)) rather than a free-form agent.

```
Character Design ─┬─► Personality ─┐
                  ├─► Backstory  ──┼─► human review ── approve ─► lessons learned
                  └─► sample images│        │
                                   │        └ reject ─► router LLM picks the owner of the feedback
                                   │                    └─► re-run only that specialist ─► review again
```

1. **Character Design** goes first, because it decides who the person is. It creates the influencer
   folder and name, then writes `CHARACTER.md`: a detailed visual identity (face, hair, body,
   signature style, distinguishing marks), with measurements and comparisons rather than loose adjectives, plus
   "consistency anchors" and exclusions. It checks the existing roster so a new influencer doesn't resemble an old one.
2. **Personality** and **Backstory** then run in parallel on top of the character. Personality writes
   `PERSONALITY.md` (values, communication style, tone) and picks the voice used for audio. Backstory
   writes `BACKSTORY.md` (life timeline, relationships, interests, anecdotes, and what is deliberately
   left open for later reveal).
3. In parallel, four **sample images** are generated from the character description, with the same
   look in different settings, clothes and poses.
4. **Human review.** The workflow pauses (a LangGraph interrupt) with all three documents. If you
   approve, it moves to lessons learned. If you reject with feedback, a small router model decides
   whether the feedback is about visuals, inner values or life story. Only that specialist reruns with
   your feedback appended, and you review again.

### Content Production: planning and posting

A **manager** coordinates two specialists and does the publishing itself.

- **Content Strategist** owns the plan: `CALENDAR.json` (dated entries with idea, content type,
  platforms, status, caption and asset links), the influencer's "journey" for the coming days, which posts
  follow, and a written content strategy.
- **Social Media Content Writer** produces *one* calendar entry at a time. It has tools for image
  generation and editing, image-to-video, speech, lip-sync and captions. It works against the persona
  files, so the face and voice stay the same across posts. It can compress its own context when it grows long.
- **Guardrails** run on the writer's output before it is accepted. If one fails, the writer is sent back to fix it:
  - a **safety check** for NSFW or harmful content
  - a **character-consistency check** that compares generated media with the reference character on
    face, skin tone, hair, build and distinguishing marks. Outfit, pose and lighting are allowed to vary.
  - a **caption check** against the personality: voice and tone, factual claims, values
- The **manager** then publishes through the Buffer MCP server, using the public asset URLs the writer
  recorded. It marks the entry `POSTED` only after it has been produced *and* published, then calls the auditor.

The manager does only what the instruction asks. A status question is answered from the calendar. A
planning request goes to the strategist and stops. Only an explicit "produce" instruction starts
production, publishing and auditing. Only one production request is ever in flight, and any email
addresses in Buffer account data are redacted before the model sees them.

**Autonomous mode.** The orchestrator can set up a daily OS-level scheduled task that runs a
non-interactive turn ("create today's posts and publish or schedule them") through the same orchestrator.
Posting then needs no one in the chat.

### Engagement & Community: insights and replies

One agent with two modes:

- **Insights** (via the orchestrator): a read-only toolset for recent media and Instagram/Threads performance.
- **Replies** (via a Meta webhook, not the orchestrator): a small FastAPI receiver verifies Meta's
  request signature, works out which influencer an account belongs to, acknowledges immediately, and
  hands each comment or mention to the agent in the background. The agent answers in the influencer's
  voice, based on the stored personality and backstory. Incoming text is treated as untrusted data, never
  as instructions. Every drafted reply passes a moderation check before it can be posted, and a failing reply is blocked.

### How the system learns

After a persona is approved, or a content cycle has run, the **Auditor** reads the checkpointed traces
of the specialists involved (tool calls, results, reasoning). It saves only lessons that **generalise**:
they must still make sense with the date, entry id, filename and influencer name removed. Each is a
success trace (a good call worth reinforcing) or a failure trace (an "avoid / prefer" pair), stored in the shared Postgres store under
`(department, influencer, "auditing")`.

Success traces are then converted into **skill files**. These are Markdown with a name and description
in the frontmatter, written in universal terms and filed under the relevant specialist's `skills/` folder
(the source trace is deleted afterwards). The specialists see these skills on their next run. The persona agents
get them injected into their prompt, and the writer lists and loads them on demand.

### State, memory and observability

- **Threads.** Every agent has its own checkpointed conversation thread in SQLite. The workflow and
  each specialist get child threads (`<thread>:backstory_agent`, ...), so a paused persona review survives a restart.
- **Shared store.** A Postgres-backed LangGraph store holds cross-agent memory such as persona details and the
  auditor's traces.
- **Models.** [models.py](src/models.py) assigns an OpenRouter model to every role. Agents have
  fallback models that take over when the primary fails.
- **Tracing.** Every run is traced in Opik, and token usage per agent is logged to `logs/token_usage.jsonl`.

## Project layout

```
src/
├── orchestration/       the orchestrator agent, its tools and system prompt
├── agents/
│   ├── persona_identity/     persona_workflow.py + character / personality / backstory specialists
│   ├── content_production/   manager + content strategist + SM content writer (guardrails, Buffer MCP)
│   └── engagement_community/ insights/reply agent + Meta webhook receiver
├── auditor/             trace extraction and lesson saving
├── self_evolution.py    success traces -> skill files
├── influencers/<name>/  per influencer: CHARACTER.md, PERSONALITY.md, BACKSTORY.md,
│                        CALENDAR.json, CONTENT_STRATEGY.md, img/, social_contents/
├── memory_store.py      shared Postgres store
├── models.py            model per role, fallbacks, Opik setup
└── cli/                 terminal chat UI, sessions, scheduling
```

Each agent folder holds its `SYSTEM_PROMPT.md`, `agent.py`, `tools.py` and `state.py`. Specialists may
also have `guardrails.py` and a `skills/` folder.
