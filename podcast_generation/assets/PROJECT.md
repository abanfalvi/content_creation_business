1. **Build a fixed, observable harness first:** planner/orchestrator, specialist agents, tools, shared state, checkpoints (saving the state of a long-running agent workflow at important points) + HITL, retries, and a verifier.
2. **Add structured memory:** retain goals, decisions, artifacts, errors, successful procedures, and compact summaries. Do not simply append all raw conversation.
3. **Add intra-task reflection:** use Reflexion-like lessons, branch-and-evaluate planning, and explicit recovery from failed tool calls.
4. **Add reusable skills:** follow the Voyager pattern by turning verified successful procedures into versioned skills that can be retrieved later. Skills should be improved later given the results of the rollouts. If the skill led to a failure, undesired step -> update the skill
5. **Add a meta-agent:** mine failures from traces and propose small changes to prompts, routing, tool selection, context management, or retry policies.
6. **Validate every candidate:** run regression tasks, safety checks, cost/latency checks, and task-specific verifiers before promotion. Keep the previous version for rollback.
7. **Only then explore recursive improvement:** allow the improvement procedure itself to propose changes to the harness optimizer, but keep execution sandboxed and promotion gated.
8. **Evaluate on long-horizon environments:** use task suites with executable or state-based success criteria, not only an LLM judge or final answer quality.

# Agent Architecture
Tier 1 — Orchestrator
Tier 2 - Content Director: Book Selection Agent, Expert Profile Builder, Script Architect (trained?) -> shared state
Tier 2 - Host Voice Agent (TTS) (trained?), Expert Voice Agent (distinct persona + TTS), Audio Engineer Agent, (Learning Bundle Creation Agent) -> shared state
Tier 2 - Distribution Director: RSS & Platform Publisher, (Social Clip Cutter), Social Media Writer,
(Newsletter Digest Agent, SEO Metadata Agent,) (Outreach Agent) -> shared state

# Workflow
Book Selection -> Expert Profile Builder -> Script drafting -> Human Review
Generate audio for host and expert -> prepare the episode (with audio engineer agent: use Auphonic API / pydub / Elevenlabs / Resemble AI -> clone the voice first ) -> Human Review
Prepare social media posts: text, (newsletter, blog -> LATER!) + create short clips (Canva mcp) -> Human Review -> publish and manage published content

# Memory and Context management strategies
Problem to solve: overpopulated threads in the checkpoints (store the most relevant facts differently) -> either compress after certain token limit is reached or create a compress tool that the agent learns when to call
The episodes of the books are independent, so memory and context needs to be handled during the process of generating the next episode. The Directors can have an overview of the steps their specialists took, extract the relevant info for self-improvement; and load the successful traces and failures at the beginning.

What to store for self-improvement in the memory: successful traces + mistakes
    Store three components:
        Title: A concise summary of the core strategy (e.g., "Navigating Multi-Step Search Filters").
        Description: A one-sentence overview of the item's purpose.
        Content: Detailed reasoning steps, decision rationales, and operational insights extracted from past experiences.

Use of flat memory (ideas): 
    Sensory memory: lightweight pre-compression removes redundant or low-value tokens
    Topic-aware short-term memory: related interaction turns are grouped into coherent topical segments.
    Long-term memory: summarized entries are stored and maintained through offline updates. 
    ---------------------------------------------------------------------------------
    Have a separate agent handling these:
    Core memory: persistent agent and user information.
    Episodic memory: timestamped events and experiences.
    Semantic memory: concepts, entities, and their meanings.
    Procedural memory: step-by-step instructions and learned routines.
    Resource memory: documents, files, and other media.
    Knowledge Vault: exact, sensitive facts that should be preserved verbatim.
    ---------------------------------------------------------------------------------
    Construct a structured memory note from LLM interactions -> 


# In context meta learning
To the unsuccessful steps, add how it should have been handled and attach this to the prompt of the model to take into account when it finds itself in this situation again

# TODO
- Not having the director to process the complete trace chunk at once