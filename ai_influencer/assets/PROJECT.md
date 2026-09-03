# TODO
- Develop Engagement & Community tier: test run, wire it into the system
- All tool calls should be seen + switch to streaming when necessary
- Memory management
- Implement self-evolution: correct failed traces

# Under development

**Summary:** Manages one or several AI-generated influencer personas across Instagram and X. The agency owns everything about the persona — face, body, personality, backstory, and voice — and keeps it visually consistent across every photo and video using a locked character model. It runs the full content operation: daily posts, DM and comment engagement, follower growth, and a monetization layer through brand partnerships, affiliate content, and paid subscription tiers.

---

**Agent Architecture**

**Tier 1 — Orchestrator**
🧠 **Influencer Brand CEO Agent** — persona portfolio strategy, platform mix, monetization roadmap, brand partnership oversight

**Tier 2 — Department Directors**

🎭 **Persona & Identity Director**
- Character Design Agent (face/body reference, visual identity)
- Visual Style Lock Agent (LoRA training for cross-image/video consistency) -> only a tool call (generates initial pictures of the designed character)
- Personality & Voice Agent (tone, speech patterns, values)
- Backstory & Lore Agent (life narrative, interests, relationships)

Workflow: design the character -> generate the images -> LLM judge -> if OK, write personality + backstory in parallel; if not, go back to character design -> human review

🎬 **Content Production Director**
- SM Content Writer Agent: Caption & Hook Writer + Photo & Video Generation
- Content Calendar Agent

💬 **Engagement & Community Director**
- DM Response & Comment Reply Agent
- Follower Growth & Community Health Agent
(- Sentiment & Community Health Monitor)

💸 **Monetization & Partnerships Director** (Comes later!)
- Brand Deal Outreach Agent
- Sponsored Content Integration Agent
- Affiliate Link Manager
- Subscription Tier Agent (Fanvue/Patreon-style paid content)

**Human checkpoint** ⚡ — persona/character design sign-off before launch + brand deal review before signing + content moderation pass on anything platform-sensitive


# Design ideas
- The managers should produce a contract for one manageable step and it should reason from the original goal, the current state, and audit reports:
{
  "subtask_id": "step-7",
  "objective": "Create and validate the output report",
  "acceptance_criteria": [
    "report.json exists",
    "report.json parses successfully",
    "all required fields are present",
    "values agree with results.csv"
  ],
  "constraints": [
    "Do not modify the raw dataset",
    "Stop after two failed repair attempts"
  ],
  "relevant_state": ["req-3", "artifact-results-csv"],
  "expected_outputs": ["report.json"]
}

- Fresh-context execution: 
    For every subtask:

    - Create a fresh executor context.
    - Provide the original task.
    - Provide the relevant portion of audited state.
    - Provide the subtask contract.
    - Give the executor tools and a bounded action/time budget.
    - Save its raw trajectory for later diagnosis.
    - Discard the raw trajectory from the next executor context.

- Independent auditing: should strictly be read-only and should inspect:
  files and schemas;
  database contents;
  test results;
  application state;
  screenshots or visual state;
  logs;
  generated artifacts;
  consistency between claimed and actual outputs.

- Recursive self-improvement loop
  editable harness surfaces:
    - manager prompt
    - executor prompt
    - auditor prompt
    - subtask contract schema
    - tool policies
    - retry limits
    - context summarization
    - recovery middleware
    - verification rules
    - routing rules

  For continual deployment, also maintain:

  a task board of recurring failures;
  research logs of attempted fixes;
  verification tests;
  branch lineage;
  temporal separation between task completion and feedback availability;
  an evolution budget;
  a mechanism for pruning obsolete or harmful skills.

Set max turn budget, if it is reached change the agent's tools to one: summarise its actions and perceived outcomes as a report -> forwarded to the next stage

## Architecture Layer
**Task management:**	Convert the user goal into requirements, dependencies, and subtasks	-> Manager, planner, dependency graph, task board -> *LEVEL*: Manager
**Agent organization:**	Define which specialized workers exist ->	Researcher, executor, coder, critic, auditor, integrator -> *LEVEL*: Specialist
**Orchestration:**	Decide when and how agents run ->	Sequential/parallel execution, retries, escalation, stopping -> *LEVEL*: Manager
**Communication:** Control what agents send to one another ->	Typed messages, handoff schemas, summaries, routing -> *LEVEL*: Manager
**Memory and state:**	Preserve useful information across contexts and tasks	-> Task state, episodic memory, semantic memory, skills, experience database -> *LEVEL*: Specialist
**Tool and environment layer:**	Let agents act safely and consistently -> Tool registry, dispatch, wrappers, sandbox, permissions, checkpoints -> *LEVEL*: Specialist
**Verification:**	Determine whether progress is real ->	Unit tests, artifact checks, independent auditors, consistency validation -> *LEVEL*: Specialist + Auditor (at the end)
**Recovery:**	Recover from failed or misleading execution -> Rollback, loop breakers, repair agents, alternative plans -> *LEVEL*: Specialist
**Harness evolution:**	Modify the current agent system -> Failure mining, patch generation, patch application, regression gates -> *LEVEL*: Manager
**Search and selection:**	Control exploration of possible designs	-> Candidate budgets, branch selection, novelty, pruning -> *LEVEL*: Specialist
**Meta-improvement:**	Improve the process that improves the harness	-> Evolving diagnosis, retrieval, allocation, proposal, and edit policies -> *LEVEL*: Meta agent
**Deployment adaptation:**	Adapt to changing task distributions ->	Task routing, specialized branches, drift detection, human escalation -> *LEVEL*: Every

## Evolution of the System
1. Analyst Agent: This agent reviews past trajectories and feedback to identify failure patterns. It maintains a "task board" that prioritizes which gaps need to be filled.
2. Researcher Agents: Operating in parallel, these agents explore potential solutions for the issues identified by the Analyst. They might search the web, test different prompting strategies, or evaluate new tools.
3. Builder Agent: Once a solution is researched and verified, the Builder implements it. This involves modifying the agent's prompts, adding new python-based skills, or updating tool registries.
4. Verifier Agent: This agent acts as a quality gate, running tests to ensure that the Builder's changes actually solve the intended problem without introducing regressions.

Crucially, this system maintains a persistent workspace across cycles.Furthermore, it uses "temporal-reveal feedback," ensuring that the agent only learns from information that would have been available at the time of the task, preventing "cheating" by looking into the future.

## Integrating Human Insight
1. Proactive Steering: Humans can review the Analyst's task board and provide high-level guidance or specific domain knowledge that the agents might be missing.
2. Reactive Unblocking: During the research phase, if an agent hits a "wall"—such as an expired API key or a paywall—it can trigger a hook to ask a human for assistance.

# Initial Phase plan (could change!)
Phase 1: Reliable long-horizon execution
Implement only:

manager;
explicit task state;
fresh-context executor;
independent auditor;
subtask contracts;
round and tool budgets;
append-only audit logs.
Use deterministic verifiers wherever possible.

Phase 2: Harness evolution
Add:

failure-trace clustering;
candidate harness patches;
held-in and held-out evaluation;
immutable harness versions;
automatic rollback;
patch provenance;
regression tests.
Start by changing prompts, retry logic, and verification middleware—not model weights.

Phase 3: Multiagent specialization
Add specialized roles such as:

planner/manager;
executor;
verifier;
researcher;
critic;
artifact validator;
recovery agent.
Use explicit contracts between agents rather than passing the full transcript to every agent. Recursive Harness Self-Improvement argues that improving these contracts and “hops”—the points at which information moves between agents—can produce better performance without simply increasing reasoning length. 

Phase 4: Recursive meta-improvement
Add:

editable analyzer, retriever, allocator, proposer, and evolver policies;
slow meta-skill updates;
branch-local improvement policies;
meta-productivity tracking;
cross-branch inspiration retrieval;
conservative promotion gates.