# Papers for a Recursive Self-Improving Multi-Agent System

A curated starting bibliography for building a multi-agent system that can improve its own prompts, memory, tools, workflows, and possibly code while completing long-horizon tasks. I prioritized papers from universities, research labs, and established organizations, and separated surveys from standalone systems and benchmarks.

> **Reading strategy:** Start with the starred papers. They provide the clearest implementation patterns for an initial system: explicit agent harness, hierarchical orchestration, persistent memory, verifiable execution, regression testing, and controlled self-improvement. Treat unrestricted self-modifying code as a research direction, not as the first production architecture.

## 1. Surveys and broad roadmaps

### ★ [A Survey of Self-Evolving Agents: What, When, How, and Where to Evolve on the Path to Artificial Super Intelligence](https://arxiv.org/abs/2507.21046) — Gao et al., Princeton University and collaborators, 2025/2026
The most directly relevant survey for this project. It organizes self-evolution around **what** changes, **when** it changes, **how** it is optimized, and **where** it is applied. The four main evolution targets are model/policy, context and memory, tools, and agent architecture. It also distinguishes intra-task evolution from between-task evolution, and textual feedback, rewards, imitation, and population-based methods. Particularly useful as a map of methods such as Reflexion, PromptBreeder, DSPy, Voyager, ADAS, AFlow, and Darwin Gödel Machine.

### ★ [Large Language Model based Multi-Agents: A Survey of Progress and Challenges](https://arxiv.org/abs/2402.01680) — Guo et al., University of Notre Dame and collaborators, 2024
A practical taxonomy of LLM multi-agent systems. It decomposes a system into the agent-environment interface, agent profiling, communication, and capability acquisition. It covers cooperative, debate, and competitive communication; layered, centralized, decentralized, and shared-message-pool structures; and adaptation through memory, self-evolution, and dynamic agent generation.

### ★ [A Survey on Agent System and Harness Design](https://arxiv.org/abs/2606.20683) — Meng et al., 2026
A recent survey organized around the **model-harness** distinction. The harness includes the execution environment, tools, context engineering, lifecycle orchestration, observability, verification, and governance around a foundation model. This is useful for designing the runtime layer separately from the model and for understanding why interface design, state tracking, and verification strongly affect long-horizon performance.

### [Survey on Evaluation of LLM-based Agents](https://arxiv.org/abs/2503.16416) — Yale University, IBM Research, Hebrew University, and collaborators, 2025
A broad evaluation survey covering planning, tool use, self-reflection, memory, web agents, software-engineering agents, scientific agents, and conversational agents. It is useful for choosing metrics and environments rather than relying only on final-answer quality. It emphasizes realistic dynamic benchmarks and executable or state-based verification.

### [Multi-Agent Collaboration Mechanisms: A Survey of LLMs](https://arxiv.org/abs/2501.06322) — 2025
Focuses specifically on collaboration mechanisms, including role specialization, communication protocols, debate, cooperation, and coordination failures. Useful when deciding whether agents should communicate through free-form conversation, structured artifacts, shared state, or explicit protocols.

### [From Static Templates to Dynamic Runtime Graphs: A Survey of Workflow Optimization for LLM Agents](https://arxiv.org/abs/2603.22386) — 2026
Surveys methods that optimize executable workflows rather than only prompts. Relevant to a harness that can add, remove, reorder, or specialize agent nodes and tool calls based on task feedback.

### [Memory in the Age of AI Agents](https://arxiv.org/abs/2512.13564) — National University of Singapore, Peking University, and collaborators, 2025
A broad survey of memory for AI agents. Relevant to long-horizon execution because it treats memory as a system for retaining and retrieving task state, experience, procedures, and user-specific information, rather than simply appending conversation history.

## 2. Recursive and self-improving agents

### ★ [Gödel Agent: A Self-Referential Agent Framework for Recursive Self-Improvement](https://arxiv.org/abs/2410.04444) — Yin et al., Peking University and collaborators, ACL 2025
One of the clearest concrete recursive-self-improvement designs. The agent can inspect its own policy and learning logic, interact with an environment to obtain a utility signal, modify its code, and recursively continue improving. Its algorithm exposes four core actions: **self-inspect**, **interact/evaluate**, **self-update**, and **continue-improve**. The implementation uses runtime inspection and dynamic code modification, plus error handling, planning before acting, code execution, and LLM calls. This is an important reference for the conceptual loop, although production use should replace unrestricted monkey-patching with versioned, sandboxed candidate harnesses.

### ★ [Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents](https://arxiv.org/abs/2505.22954) — Zhang et al., Jeff Clune’s group, 2025/2026
A self-referential coding-agent system that writes and modifies its own code. Instead of requiring a formal proof that a change is beneficial, it uses empirical evaluation: generate a modification, run it on coding tasks, retain promising variants, and explore further. The evolutionary archive and empirical selection are directly relevant to a safe harness optimizer with candidate versions, regression tests, lineage, and rollback.

### ★ [Self-Harness: Harnesses That Improve Themselves](https://arxiv.org/abs/2606.09498) — 2026
Proposes a self-improvement loop internal to the target agent rather than relying on a stronger external model. The loop has three useful stages: **weakness mining** from execution traces, **harness proposal** that produces minimal changes tied to observed failures, and **proposal validation** through regression testing. This is a strong design pattern for gradually improving prompts, routing, retry policies, tools, and context handling without allowing arbitrary uncontrolled rewrites.

### [Recursive Harness Self-Improvement](https://arxiv.org/abs/2607.15524) — 2026
Studies recursive improvement of the harness itself, treating the harness as a specification of the agent loop and iteratively refining it using feedback over its revision history. The key idea is that harnesses are not just inference-time scaffolds: their traces can become training or improvement data. Useful for designing a meta-agent that improves orchestration and execution policy across generations.

### [Recursive Agent Harnesses](https://arxiv.org/abs/2606.13643) — 2026
Connects coding-agent harnesses with recursive language-model execution over large inputs. The paper is relevant to tasks where the agent must repeatedly delegate work over files, documents, or data slices, aggregate intermediate results, and maintain state beyond one context window.

### [SIA: Self Improving AI with Harness & Weight Updates](https://arxiv.org/abs/2605.27276) — 2026
Presents a configurable loop with a meta-agent, a task-specific agent, and a feedback agent. After execution, the feedback agent selects whether to update the harness, update model weights, or follow another improvement path. This separation is useful for a system in which lightweight prompt/workflow changes happen frequently while expensive model training happens only when justified by accumulated evidence.

### [Self-Taught Optimizer (STOP): Recursively Self-Improving Code Generation](https://arxiv.org/abs/2310.02304) — Zelikman et al., 2023
A foundational example of recursive optimization in which the optimizer improves the code-generation process used to create optimizers. It is narrower than a general multi-agent harness, but provides a clean conceptual precedent for optimizing the improvement procedure itself.

### [Can Large Language Models Invent Algorithms to Improve Themselves? Algorithm Discovery for Recursive Self-Improvement through Reinforcement Learning](https://arxiv.org/abs/2410.15639) — NAACL 2025
Studies using reinforcement learning to discover algorithms that improve the model or agent. Relevant to the longer-term possibility of learning orchestration or optimization policies rather than hand-authoring every update rule.

### [Symbolic Learning Enables Self-Evolving Agents](https://arxiv.org/abs/2406.18532) — Zhou et al., 2024
Explores symbolic, inspectable updates for self-evolving agents. This is useful as a less opaque alternative to rewriting all behavior in natural-language prompts: learned rules, procedures, and structured policies can be inspected, tested, and selectively updated.

## 3. Agent architecture and multi-agent workflow construction

### ★ [AgentSquare: Automatic LLM Agent Search in Modular Design Space](https://arxiv.org/abs/2410.06153) — 2024
Searches over modular agent designs rather than optimizing one fixed prompt. The modular perspective is directly applicable to a harness: represent planning, retrieval, tool use, reflection, verification, and delegation as replaceable components, then evaluate candidate combinations on a task suite.

### ★ [ADAS: Automated Design of Agentic Systems](https://arxiv.org/abs/2408.08435) — Hu et al., 2024
Uses an LLM meta-agent to generate and evaluate agent programs. It provides a practical template for architecture search: describe the design space, generate candidate agent code or workflows, execute candidates, score them, and retain strong designs. Pairing this with sandboxing and regression tests makes it a useful starting point for automated harness design.

### [AFlow: Automating Agentic Workflow Generation](https://arxiv.org/abs/2410.10762) — 2024
Applies search to generate agentic workflows, including the structure and ordering of calls. It is especially relevant when the system should dynamically choose between sequential planning, parallel specialist calls, iterative critique, and verification.

### ★ [MetaGPT: Meta Programming for Multi-Agent Collaborative Framework](https://arxiv.org/abs/2308.00352) — Hong et al., 2023
A role-based software-development system that encodes standardized operating procedures into agent prompts and intermediate artifacts. It shows how to make multi-agent collaboration more reliable by replacing unconstrained chat with explicit roles, workflow stages, shared message pools, and structured deliverables.

### [AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation](https://arxiv.org/abs/2308.08155) — Microsoft Research and collaborators, 2023
A general framework for defining agents, tools, human participation, and conversation patterns. Useful as a baseline implementation model for agent-to-agent dialogue, group chat, tool execution, and human-in-the-loop control.

### [ChatDev: Communicative Agents for Software Development](https://arxiv.org/abs/2307.07924) — Qian et al., 2023
Models a software company with role-specialized agents and structured communication phases. It is a clear example of decomposing a complex task into a sequence of specialist interactions and artifact handoffs.

### [Multi-Agent Systems: From Classical Paradigms to Large Foundation Model-Enabled Futures](https://arxiv.org/abs/2604.18133) — 2026
A broader survey connecting classical multi-agent concepts with foundation-model agents. Useful for grounding design choices in established ideas such as coordination, negotiation, decentralization, communication, and collective behavior instead of treating every LLM workflow as a novel paradigm.

## 4. Long-horizon execution, memory, and experience

### ★ [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291) — Wang et al., NVIDIA and collaborators, 2023
A strong implementation pattern for continual improvement: an automatic curriculum, an iterative skill-generation loop, a skill library, and execution feedback. The agent stores reusable executable skills and retrieves them for later tasks. The same pattern can support a content-production or research system that accumulates tested procedures instead of merely storing transcripts.

### ★ [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366) — Shinn et al., 2023
Uses verbal feedback and episodic memory to let an agent reflect on failures and improve later attempts without changing model weights. This is a lightweight first stage for self-improvement and can be implemented before introducing learned policies or code evolution.

### [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — Yao et al., 2022
The core reasoning-and-action loop for tool-using agents. The paper interleaves reasoning traces with actions and observations. It is a foundational building block for any harness that must execute tools, observe results, recover from errors, and continue toward a goal.

### [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://arxiv.org/abs/2305.10601) — Yao et al., 2023
Introduces explicit search over multiple reasoning branches with evaluation and backtracking. The ideas transfer to long-horizon planning: branch when uncertainty is high, evaluate partial plans, and prune failed trajectories rather than committing to one brittle chain.

### [Context as a Tool: Context Management for Long-Horizon SWE-Agents](https://arxiv.org/abs/2512.22087) — 2025
Treats context management as an explicit capability/tool for long-running software-engineering agents. Relevant patterns include summarizing and retrieving state, deciding what to preserve, and using externalized context instead of forcing the entire trajectory into one prompt.

### [SWE-bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?](https://arxiv.org/abs/2509.16941) — 2025
A longer-horizon software-engineering evaluation designed to expose failures that are hidden by short issue-resolution tasks. Useful for testing whether an agent can maintain plans, edit multiple files, run tests, recover from mistakes, and finish a substantial change.

### [SWE-EVO: Benchmarking Coding Agents in Long-Horizon Software Evolution Scenarios](https://arxiv.org/abs/2512.18470) — 2025
Evaluates sustained software evolution rather than isolated bug fixes. It is a useful benchmark model for measuring whether an agent can preserve project-level state and make coherent changes across a sequence of related tasks.

### [DeepPlanning: Benchmarking Long-Horizon Agentic Planning with Verifiable Constraints](https://arxiv.org/abs/2601.18137) — Alibaba Group, 2026
Targets planning with global constraints such as time and budget, rather than only local step prediction. This is useful for designing a planner that tracks resource constraints, dependencies, deadlines, and invariant requirements throughout execution.

### [AgentBench: Evaluating LLMs as Agents](https://arxiv.org/abs/2308.03688) — Liu et al., ICLR 2024
A multi-environment benchmark spanning different agent tasks and interfaces. Useful for evaluating general agent capabilities across environments rather than optimizing only for a single application.

## Notes

- Several harness and recursive-self-improvement papers are very recent preprints. Their mechanisms are promising but should be treated as research prototypes until independently reproduced.
- “Self-improving” can mean very different things: better in-context behavior, persistent memory, new tools, workflow search, policy/weight updates, or unrestricted code modification. The survey taxonomy above helps keep these distinct.
- For a first implementation, prompt/workflow/memory evolution with regression testing is substantially easier to control than direct self-modification of executable code or model weights.

_Last curated from arXiv, alphaXiv, Hugging Face paper search, and web search._

## Sources used

- [alphaXiv paper discovery](https://www.alphaxiv.org/)
- [Hugging Face Papers](https://huggingface.co/papers)
- [arXiv](https://arxiv.org/)

## Project context

The current project architecture in [`PROJECT.md`](PROJECT.md) already has an orchestrator, content director, production director, and distribution director. The papers above are especially relevant to turning those fixed tiers into a stateful, verifiable, long-horizon workflow with specialist agents and a controlled improvement loop.

## GitHub repositories for implementation inspiration

These repositories are not all direct implementations of recursive self-improvement. They cover complementary pieces of the target system: multi-agent role design, workflow graphs, state and persistence, tools and sandboxes, long-running execution, and autonomous improvement loops.

### ★ [AgentScope](https://github.com/agentscope-ai/agentscope) — Alibaba / DAMO Academy ecosystem

One of the closest matches for a serious, general-purpose multi-agent runtime. The current AgentScope 2.0 README highlights an event system, human-in-the-loop support, fine-grained permissions, multi-tenancy and multi-session serving, isolated workspaces/sandboxes, middleware hooks, RAG, long-term memory, MCP and skill hubs, agent teams, task planning, and background task offloading. The repository has `src/`, `examples/`, `tests/`, deployment examples, and a web UI. **Study it for:** runtime abstractions, event-driven execution, tool permissions, sandbox boundaries, persistent sessions, and leader-agent/worker-team patterns.

### ★ [LangGraph](https://github.com/langchain-ai/langgraph) — LangChain

A low-level orchestration framework for stateful agents and long-running workflows. Its core design emphasizes durable execution, checkpointing and resumption, human interrupts, short- and long-term memory, branching, subgraphs, and tracing. It is a particularly strong candidate for the deterministic harness layer around your podcast agents: represent the content, production, and distribution directors as stateful graph nodes, and persist checkpoints between long tasks. The repository includes `libs/`, `examples/`, `docs/`, and agent instructions.

### ★ [CrewAI](https://github.com/crewAIInc/crewAI) and [CrewAI examples](https://github.com/crewAIInc/crewAI-examples) — CrewAI

Useful for the distinction between autonomous **Crews** and deterministic, event-driven **Flows**. Crews provide role-based collaboration and delegation; Flows provide state, branching, routing, triggers, and production control. The README includes a structured-state example combining a Flow with several Crews, plus support for tools, memory, checkpointing, async execution, MCP/A2A, human input, and observability. **Study it for:** mapping your existing director hierarchy into nested agent teams while keeping business logic and guardrails outside the LLM.

### ★ [MetaGPT](https://github.com/FoundationAgents/MetaGPT) — FoundationAgents / DeepWisdom

A mature role-based multi-agent software-company implementation. It turns a one-line requirement into artifacts through product manager, architect, project manager, and engineer roles coordinated by explicit standard operating procedures. The repository has a substantial `metagpt/` package, `examples/`, `config/`, `docs/`, and tests. **Study it for:** role boundaries, SOP-driven coordination, artifact handoffs, shared message pools, and how a high-level orchestrator can turn a vague goal into a staged production pipeline.

### ★ [AutoGen](https://github.com/microsoft/autogen) and [Magentic-One](https://github.com/microsoft/autogen/tree/main/python/packages/magentic-one-cli) — Microsoft Research / Microsoft

AutoGen provides layered core, agent-chat, and extension APIs for event-driven agents, group chats, tools, code execution, MCP, and human participation. Its README currently marks the project as **maintenance mode** and recommends Microsoft Agent Framework for new projects, but the code and Magentic-One package remain valuable references for multi-agent orchestration. **Study it for:** message passing, agent tools, group-chat patterns, runtime separation, and a research-oriented multi-agent team that combines browsing, code execution, and file handling.

### [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) — Microsoft

The successor recommended by Microsoft for new work after AutoGen. It is worth comparing with LangGraph and AgentScope if you want a production-oriented Microsoft stack, especially around multi-agent orchestration, model-provider support, MCP/A2A interoperability, and enterprise deployment patterns.

### ★ [CAMEL-AI](https://github.com/camel-ai/camel) — CAMEL-AI research community

A broad research platform rather than only a small orchestration library. The repository explicitly emphasizes **evolvability**, **scalability**, and **statefulness**, and contains agents, agent societies, workforce coordination, memory, storage, tools, runtime/process management, RAG, benchmarks, human-in-the-loop support, data generation, and simulated environments. It also includes a multi-agent research assistant example and a role-playing scraper for report and knowledge-graph generation. **Study it for:** reusable agent society abstractions, dynamic communication, stateful memory, synthetic data generation, and research/evaluation infrastructure.

### [OpenHands](https://github.com/OpenHands/OpenHands) and [OpenHands Agent Server](https://github.com/OpenHands/software-agent-sdk/tree/main/openhands-agent-server/openhands/agent_server) — OpenHands

One of the best references for a long-running agent harness rather than a simple agent loop. The current Agent Canvas architecture runs multiple agent backends locally, in Docker, on VMs, or in the cloud, and adds scheduled or event-triggered automations connected to services such as Slack, GitHub, and Linear. The repository has a large application, server, sandbox, tools, specs, tests, and deployment structure. **Study it for:** agent-server separation, backend abstraction, persistent sessions, automation triggers, isolated execution, multi-project workspaces, and operational concerns.

### ★ [SWE-agent](https://github.com/SWE-agent/SWE-agent) and [mini-SWE-agent](https://github.com/SWE-agent/mini-SWE-agent) — Princeton University / Stanford University

A research-grade example of designing the **agent-computer interface** as part of the harness. It supports configurable tool environments, YAML-based agent configuration, trajectories, batch evaluation, real repository interaction, and test-based validation. The project recommends mini-SWE-agent for new users because it is much simpler while preserving strong performance. **Study it for:** tool interface design, trajectory logging, reproducible evaluation, environment adapters, error recovery, and separating agent policy from execution infrastructure.

### [Hugging Face smolagents](https://github.com/huggingface/smolagents) — Hugging Face

Small enough to read and modify, but still includes code agents, tool-calling agents, multi-agent hierarchies, MCP/tool collections, Hub-shared agents and tools, remote execution, and sandbox integrations such as Docker and E2B. Its `agents.py` is intentionally compact. **Study it for:** a minimal agent loop, code-as-action execution, memory handling, sub-agent hierarchies, and how to keep the core abstractions understandable before scaling the architecture.

### [Agentic AI Scientist](https://github.com/SakanaAI/AI-Scientist) — Sakana AI

An end-to-end autonomous scientific-discovery pipeline. It generates ideas, writes and executes experiments, analyzes results, produces papers, and runs automated reviews. It includes templates, experiment runners, literature search, review agents, output artifacts, and containerization guidance. **Study it for:** long-horizon artifact-producing loops, experiment/evaluation cycles, domain templates, structured output directories, and autonomous research pipelines. Treat its code execution as high risk and use containers with restricted network access.

### Research-oriented examples

For a lighter research-oriented architecture, inspect the research-assistant examples in [CAMEL](https://github.com/camel-ai/camel/tree/master/examples/usecases/multi_agent_research_assistant), [MetaGPT](https://github.com/FoundationAgents/MetaGPT/tree/main/examples), and [CrewAI examples](https://github.com/crewAIInc/crewAI-examples). These are more useful for the project's content-research and script-generation stages than a pure coding-agent framework.

### [Standalone Orchestrator](https://github.com/TenchiNeko/standalone-orchestrator) — local-model reference

A small local-LLM system organized around **Plan → Build → Test → Fix**, with Qwen models and an explicit multi-agent orchestrator. It is useful for understanding how to keep the architecture lightweight and VRAM-conscious while retaining validation loops. It is a community project with a much smaller maintenance footprint than the institutional frameworks above, so use it for ideas rather than as a dependency.

## Suggested repository study order for this project

1. **LangGraph or AgentScope:** implement durable state, checkpoints, events, permissions, and background execution.
2. **MetaGPT or CrewAI:** model the Content Director, Production Director, and Distribution Director as specialized teams with explicit artifacts and SOPs.
3. **SWE-agent / OpenHands:** borrow execution-harness ideas: tools, sandboxes, trajectories, retries, observability, and verification.
4. **CAMEL-AI:** add memory, agent societies, dynamic collaboration, and research-oriented evaluation.
5. **AI Scientist:** study how to build a long-horizon artifact pipeline with iterative execution, grading, and review.
6. **Gödel Agent / Darwin Gödel Machine concepts from the papers above:** add a separate, gated meta-agent that proposes harness changes and promotes only candidates that pass regression tests.

## Important maturity and safety notes

- **AutoGen is in maintenance mode.** Use it primarily as an architectural reference or migrate to Microsoft Agent Framework for a new Microsoft-based implementation.
- **Frameworks are not interchangeable drop-ins.** LangGraph is strongest as low-level stateful orchestration; CrewAI is convenient for Crews plus Flows; MetaGPT is strongest for SOP and role-based artifact pipelines; AgentScope is strongest as a broader runtime/service foundation.
- **Do not run arbitrary model-generated code on the host.** OpenHands, SWE-agent, smolagents, and AI Scientist all demonstrate why tool execution needs sandboxing, resource limits, filesystem restrictions, network policy, and human approval for dangerous operations.
- **Do not begin with recursive code rewriting.** First version the prompts, graph definitions, tools, memory schemas, and routing policies. Let a meta-agent propose changes, then run regression tasks, safety checks, cost checks, and artifact-quality checks before promotion.
