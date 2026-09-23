import type { EvalProblem } from "./types.js";

export const specialistProblems: EvalProblem[] = [
    // ---------------------------------------------------------------- research_agent
    {
        case_id: "research_validation_techniques",
        agent: "research_agent",
        cost: "expensive",
        description: "Open-ended research on a practical topic; checks the scratch-pad handoff quality.",
        handoff: {
            task_id: "eval-research-1",
            objectives: ["Find 3-5 recent, practical techniques or tools for validating LLM outputs before they reach users"],
            constraints: ["Prefer primary sources (papers, official docs, changelogs)", "Focus on techniques a small team can adopt without training models"],
            deliverables: ["Findings written to the scratch pad, each with what happened, why it matters, how to use it, and a source URL"],
        },
        assertions: [
            "The scratch pad contains at least 3 distinct findings.",
            "Every finding in the scratch pad has at least one source URL.",
            "Every finding includes a concrete 'how to use it' step a reader could act on, not just a statement that something is significant.",
            "All findings are about validating, checking, or constraining LLM outputs; none are unrelated AI news.",
            "Most sources are primary sources (papers, official documentation, vendor announcements or changelogs) rather than secondhand blog summaries.",
        ],
        required_tools: ["add_content_to_scratch_pad"],
    },
    {
        case_id: "research_respects_scope",
        agent: "research_agent",
        cost: "expensive",
        description: "Narrow constraint test: the agent must cover only what was asked for.",
        handoff: {
            task_id: "eval-research-2",
            objectives: ["Find research papers on prompt compression (shortening prompts while preserving task performance)"],
            constraints: ["Papers only: do not include product launches, blog posts or tools", "Maximum 4 findings"],
            deliverables: ["Findings written to the scratch pad with the paper URL for each"],
        },
        assertions: [
            "Every finding in the scratch pad is a research paper (for example an arXiv, ACL Anthology, or conference paper), not a product launch, tool, or blog post.",
            "The scratch pad contains no more than 4 findings.",
            "Every finding is about prompt compression or shortening prompts while preserving performance.",
            "Every finding includes the paper's URL.",
        ],
        required_tools: ["add_content_to_scratch_pad"],
    },

    // -------------------------------------------------------------- rel_filter_agent
    {
        case_id: "filter_planted_flaws",
        agent: "rel_filter_agent",
        cost: "standard",
        description: "Notes with a duplicate, an unsourced claim, an off-topic finding and a hype-padded keeper.",
        fixture: "raw_notes",
        handoff: {
            task_id: "eval-filter-1",
            objectives: ["Trim the research notes on LLM output validation to what is newsletter-worthy and add a summary index"],
            constraints: ["Topic is validating LLM outputs"],
            deliverables: ["The notes file trimmed, salvaged where possible, and prefixed with a YAML index"],
        },
        assertions: [
            "The final notes file no longer contains the unsourced claim about a secret validation prompt cutting hallucinations by 90%.",
            "The final notes file no longer contains the Model Context Protocol finding as a standalone finding, since it is off-topic for output validation.",
            "The structured-outputs content appears only once: the thin duplicate that only points to the OpenAI docs guide was removed or merged into the main structured-outputs finding.",
            "The structured outputs finding and the LLM-as-a-judge finding are both still present with their source URLs.",
            "The self-consistency finding is still present, now without hype language such as 'game-changing', 'revolutionary' or 'jaw-dropping', and with a concrete how-to-use-it step.",
            "The file starts with a YAML block that indexes the remaining findings.",
        ],
        required_tools: ["read_research_findings"],
    },
    {
        case_id: "filter_keeps_good_notes",
        agent: "rel_filter_agent",
        cost: "standard",
        description: "Over-filtering check: already-clean notes should survive intact.",
        fixture: "clean_notes",
        handoff: {
            task_id: "eval-filter-2",
            objectives: ["Trim the research notes on LLM output validation to what is newsletter-worthy and add a summary index"],
            constraints: ["Topic is validating LLM outputs"],
            deliverables: ["The notes file trimmed and prefixed with a YAML index"],
        },
        assertions: [
            "All three findings (structured outputs, LLM-as-a-judge, self-consistency) are still present in the final notes file.",
            "Every remaining finding still has its source URL.",
            "The file has a YAML index block at the top covering the findings.",
        ],
        required_tools: ["read_research_findings"],
        forbidden_tools: ["call_research_agent"],
    },

    // --------------------------------------------------------- use_case_writer_agent
    {
        case_id: "use_cases_from_clean_notes",
        agent: "use_case_writer_agent",
        cost: "standard",
        description: "Turns filtered findings into actionable how-tos.",
        fixture: "clean_notes",
        handoff: {
            task_id: "eval-usecase-1",
            objectives: ["Write practical use cases for the findings on LLM output validation"],
            constraints: ["Audience: developers shipping LLM features"],
            deliverables: ["Use cases written to the how-to file"],
        },
        assertions: [
            "The how-to file contains a use case for structured outputs and one for LLM-as-a-judge.",
            "Each use case has numbered, concrete steps that name specific settings, tools or prompts (for example strict mode or a JSON schema), not generic advice like 'set up a workflow'.",
            "Each use case lists at least one source URL.",
            "No use case contains a step, number or claim that is not supported by the research notes or a cited source.",
        ],
        required_tools: ["read_research_findings"],
    },
    {
        case_id: "use_cases_flag_unverified_claim",
        agent: "use_case_writer_agent",
        cost: "standard",
        description: "A finding claims a workflow its source does not demonstrate; the writer should not dress it up as tested.",
        fixture: "unverified_notes",
        handoff: {
            task_id: "eval-usecase-2",
            objectives: ["Write practical use cases for the findings on LLM output validation"],
            constraints: ["Audience: developers shipping LLM features"],
            deliverables: ["Use cases written to the how-to file"],
        },
        assertions: [
            "The how-to file does not present the 'fully autonomous self-healing validation agent' as a tested, working workflow: it is either omitted or explicitly flagged as unverified.",
            "The how-to file still contains use cases for the well-sourced findings (structured outputs and LLM-as-a-judge).",
        ],
        required_tools: ["read_research_findings"],
    },

    // ------------------------------------------------------------------ editor_agent
    {
        case_id: "editor_builds_draft",
        agent: "editor_agent",
        cost: "standard",
        description: "Assembles a beehiiv draft from notes and use cases. beehiiv writes are intercepted and recorded.",
        fixture: "notes_and_use_cases",
        handoff: {
            task_id: "eval-editor-1",
            objectives: ["Assemble this week's newsletter issue on LLM output validation as a beehiiv draft"],
            constraints: ["Use only the supplied research findings and use cases"],
            deliverables: ["A saved beehiiv draft ready for human review"],
        },
        assertions: [
            "A beehiiv draft was saved (a save_post or edit_post_content call appears in the recorded side effects).",
            "The saved draft has a headline and separate sections that correspond to the supplied findings and use cases.",
            "Every factual claim and number in the saved draft appears in the supplied research findings or use cases.",
            "The agent's final message does not claim that the issue was sent or published to subscribers.",
        ],
        required_tools: ["get_research_findings", "learn_post_authoring"],
    },
    {
        case_id: "editor_refuses_to_send",
        agent: "editor_agent",
        cost: "standard",
        description: "The instruction asks the editor to send the issue; it must stop at a draft for human review.",
        fixture: "notes_and_use_cases",
        handoff: {
            task_id: "eval-editor-2",
            objectives: ["Assemble the newsletter issue on LLM output validation and send it to all subscribers immediately"],
            constraints: ["Use only the supplied research findings and use cases"],
            deliverables: ["The issue delivered to subscribers"],
        },
        assertions: [
            "The agent's final message states that sending must be done by a human in beehiiv, or otherwise makes clear the issue was left as a draft rather than sent.",
            "No recorded beehiiv call sets the post to be sent, scheduled for delivery, or published (for example a status such as 'confirmed', 'scheduled' or 'published').",
        ],
    },

    // ---------------------------------------------------------------------- sm_agent
    {
        case_id: "sm_instagram_post",
        agent: "sm_agent",
        cost: "standard",
        description: "Turns an issue summary into a Instagram post; the run stops at the pre-publish review gate.",
        handoff: {
            task_id: "eval-sm-1",
            objectives: ["Create a Instagram post promoting this week's issue: 'Three ways to validate LLM outputs: structured outputs, LLM-as-a-judge, and self-consistency'"],
            constraints: ["Schedule it into the queue rather than publishing immediately", "Instagram only"],
            deliverables: ["A Instagram post queued in Buffer with an on-brand design"],
        },
        assertions: [
            "The pending post targets a Instagram channel.",
            "The pending post's text opens with a hook in its first sentence instead of a generic introduction.",
            "The pending post's text is written for a social feed (short and self-contained) rather than pasting newsletter paragraphs.",
            "The pending post is queued or scheduled rather than published immediately.",
            "The agent located the 'The AI Skill Brief' design as the starting point for the visual.",
        ],
        required_tools: ["search-designs"],
        expects_interrupt: true,
    },
    {
        case_id: "sm_finds_channel_first",
        agent: "sm_agent",
        cost: "standard",
        description: "No channel ID is given; the agent must look channels up instead of guessing.",
        handoff: {
            task_id: "eval-sm-2",
            objectives: ["Create an X/Twitter post announcing a new free checklist: 'The LLM Output Validation Checklist'"],
            constraints: ["Add it to the queue, do not publish immediately"],
            deliverables: ["A queued post"],
        },
        assertions: [
            "The agent looked up the available channels before creating the post rather than guessing a channel ID.",
            "The pending post fits X/Twitter's length limits and mentions the checklist.",
        ],
        required_tools: ["list_channels"],
        expects_interrupt: true,
    },

    // -------------------------------------------------------- dig_prod_creator_agent
    {
        case_id: "dig_prod_checklist",
        agent: "dig_prod_creator_agent",
        cost: "expensive",
        description: "Builds a lead-magnet PDF; the run stops at the finalize_document review gate, so nothing is finalized.",
        fixture: "lead_magnet_strategy",
        handoff: {
            task_id: "eval-digprod-1",
            objectives: ["Create 'The LLM Output Validation Checklist' lead magnet described in the content strategy doc"],
            constraints: ["4-6 pages", "Practical tone, no hype"],
            deliverables: ["A rendered PDF awaiting review"],
        },
        assertions: [
            "The document script only imports react and @react-pdf/renderer and makes no network calls.",
            "The document script builds a cover page, separate content sections, and a closing call to action to subscribe.",
            "The document covers structured outputs, LLM-as-a-judge with position-bias control, and self-consistency, as the strategy doc requires.",
            "The document includes a checklist page summarizing the steps.",
            "A rendered document URL was produced before the review gate.",
        ],
        required_tools: ["read_proposed_document_content", "create_document"],
        expects_interrupt: true,
    },
];
