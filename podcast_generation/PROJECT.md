1. **Build a fixed, observable harness first:** planner/orchestrator, specialist agents, tools, shared state, checkpoints (saving the state of a long-running agent workflow at important points) + HITL, retries, and a verifier.
2. **Add structured memory:** retain goals, decisions, artifacts, errors, successful procedures, and compact summaries. Do not simply append all raw conversation.
3. **Add intra-task reflection:** use Reflexion-like lessons, branch-and-evaluate planning, and explicit recovery from failed tool calls.
4. **Add reusable skills:** follow the Voyager pattern by turning verified successful procedures into versioned skills that can be retrieved later.
5. **Add a meta-agent:** mine failures from traces and propose small changes to prompts, routing, tool selection, context management, or retry policies.
6. **Validate every candidate:** run regression tasks, safety checks, cost/latency checks, and task-specific verifiers before promotion. Keep the previous version for rollback.
7. **Only then explore recursive improvement:** allow the improvement procedure itself to propose changes to the harness optimizer, but keep execution sandboxed and promotion gated.
8. **Evaluate on long-horizon environments:** use task suites with executable or state-based success criteria, not only an LLM judge or final answer quality.

# Agent Architecture
Tier 1 — Orchestrator
Tier 2 - Content Director: Book Selection Agent, Expert Profile Builder, Script Architect (trained?) -> shared state
Tier 2 - Production Director: Host Voice Agent (TTS) (trained?), Expert Voice Agent (distinct persona + TTS), Audio Engineer Agent, (Learning Bundle Creation Agent) -> shared state
Tier 2 - Distribution Director: RSS & Platform Publisher, (Social Clip Cutter), Social Media Writer,
(Newsletter Digest Agent, SEO Metadata Agent,) (Outreach Agent) -> shared state

# Workflow
Book Selection -> Expert Profile Builder -> Script drafting -> Human Review
Generate audio for host and expert -> prepare the episode (with audio engineer agent: use Auphonic API / pydub / Elevenlabs / Resemble AI -> clone the voice first ) -> Human Review
Prepare social media posts: text, (newsletter, blog -> LATER!) + create short clips (Canva mcp) -> Human Review -> publish and manage published content