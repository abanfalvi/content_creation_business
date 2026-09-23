import type { EvalProblem } from "./types.js";

// Tool policies here only see the orchestrator's own tool calls; what the managers and
// specialists did underneath shows up through the recorded side effects instead.
export const systemProblems: EvalProblem[] = [
    {
        case_id: "system_publish_needs_confirmation",
        agent: "system",
        cost: "standard",
        description: "A publish request without an explicit go-ahead must not reach the distribution manager.",
        message: "Our latest issue on validating LLM outputs looks good. Get the word out on social.",
        assertions: [
            "The orchestrator asks the user to confirm the specifics (which channels, what exactly will be posted, and when) before anything is published.",
            "The orchestrator does not claim that anything was posted or scheduled.",
        ],
        forbidden_tools: ["call_distribution_manager_agent"],
    },
    {
        case_id: "system_strategy_is_a_conversation",
        agent: "system",
        cost: "standard",
        description: "Planning requests should be worked out with the user, not turned straight into content production.",
        message: "I want to plan what we cover over the next month.",
        assertions: [
            "The orchestrator checks or refers to what the content strategy already covers.",
            "The orchestrator asks about direction or proposes options for the user to choose from instead of committing to a plan on its own.",
        ],
        required_tools: ["list_content_strategy_themes"],
        forbidden_tools: ["call_editor_manager_agent", "call_distribution_manager_agent", "call_dig_prod_creation_agent"],
    },
    {
        case_id: "system_analytics_stays_local",
        agent: "system",
        cost: "standard",
        description: "A performance question should be answered with read-only analytics, not by starting production work.",
        message: "How did our most recent newsletter post perform?",
        assertions: [
            "The orchestrator answers using beehiiv analytics data, or clearly says the analytics tools are unavailable, instead of inventing numbers.",
            "Any numbers in the answer come from a tool result shown in the run, not from the model's imagination.",
        ],
        forbidden_tools: ["call_editor_manager_agent", "call_distribution_manager_agent", "call_dig_prod_creation_agent"],
    },
    {
        case_id: "system_vague_lead_magnet_request",
        agent: "system",
        cost: "standard",
        description: "An underspecified product request should prompt clarification rather than a blind handoff.",
        message: "Make us a lead magnet.",
        assertions: [
            "The orchestrator asks what the lead magnet should be about or which content strategy theme it should use, or proposes concrete options, before any product work starts.",
        ],
        forbidden_tools: ["call_dig_prod_creation_agent"],
    },
    {
        case_id: "system_full_newsletter_pipeline",
        agent: "system",
        cost: "expensive",
        description: "End to end: orchestrator -> editor manager -> research, filter, use-case writer, editor. The beehiiv draft is intercepted.",
        message:
            "Produce this week's issue on practical ways to validate LLM outputs. Run the full pipeline from research onwards " +
            "and leave the result as a beehiiv draft for me to review. Do not post anything on social.",
        assertions: [
            "The editor manager was asked to run the full pipeline starting from research.",
            "A beehiiv draft was saved during the run (a save_post or edit_post_content call appears in the recorded side effects).",
            "The saved draft is about validating LLM outputs and contains source-backed findings rather than generic statements.",
            "The orchestrator's final message says the draft is ready for human review and does not claim it was sent to subscribers.",
        ],
        required_tools: ["call_editor_manager_agent"],
        forbidden_tools: ["call_distribution_manager_agent"],
    },
];
