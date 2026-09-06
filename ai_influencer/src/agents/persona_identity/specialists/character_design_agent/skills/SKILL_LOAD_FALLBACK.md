---
name: Fallback to Core Principles When Reference Skills Are Missing
description: Ensures task continuity when an expected specialist skill is unavailable, by leveraging foundational operating principles and existing roster data instead. Use this the moment load_skill_content returns empty or fails to find a requested skill.
---

# Fallback to Core Principles When Reference Skills Are Missing

When a requested skill fails to load or comes back empty, don't halt the task or guess at what the missing skill might have said.

1. **Acknowledge the gap immediately.** Note that the skill is unavailable and move on — don't retry the same load repeatedly or stall waiting for it to appear.
2. **Fall back to the agent's own built-in operating principles and system constraints** (the ones already given in the system prompt) as the primary scaffolding for whatever decision the missing skill would have informed.
3. **Pull in whatever grounding data already exists in the current session** — previously established influencer profiles, character files already read via `read_character_design`, or roster comparisons already run via `check_existing_influencers` — and use that as supporting context in place of the missing skill.
4. **Continue producing the full expected output at the same quality bar.** A missing skill is a degraded-information state, not a reason to produce a partial, hedged, or lower-effort result.
