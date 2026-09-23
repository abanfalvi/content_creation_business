export type AgentName =
    | "research_agent"
    | "rel_filter_agent"
    | "use_case_writer_agent"
    | "editor_agent"
    | "sm_agent"
    | "dig_prod_creator_agent"
    | "system";

export type HandoffContract = {
    task_id: string;
    objectives: string[];
    constraints: string[];
    deliverables: string[];
};

export type Fixture = "raw_notes" | "clean_notes" | "unverified_notes" | "notes_and_use_cases" | "lead_magnet_strategy";

export type EvalProblem = {
    case_id: string;
    agent: AgentName;
    // "expensive" cases run the web-search pipeline, e2b, or the whole multi-agent chain;
    // they only run with --include-expensive.
    cost: "standard" | "expensive";
    description: string;
    // Specialists receive a handoff contract, exactly as their manager sends it; the
    // system suite receives a user message to the orchestrator.
    handoff?: HandoffContract;
    message?: string;
    fixture?: Fixture;
    // Natural-language checks graded by the LLM judge against the run's artifacts.
    assertions: string[];
    // Deterministic checks against the directly invoked agent's own tool calls.
    required_tools?: string[];
    forbidden_tools?: string[];
    // The run is expected to stop at a human-review gate instead of finishing.
    expects_interrupt?: boolean;
};
