---
name: performance-review
description: Routine for reviewing how the newsletter and its past issues actually performed, and turning the numbers into a content-strategy conclusion. Use when the user asks how a post or theme did, whether the newsletter is working, or whether to run more (or less) coverage of a theme — and before recommending a theme change.
---

# Performance review

Strategy should be grounded in what happened for this publication's own readers, not in what "should" resonate. The numbers are a tool call away, so check them before recommending more or less of a theme. Everything here is read-only: it informs the conversation and changes nothing.

Pass the newsletter's beehiiv publication ID to every beehiiv tool that asks for one, and never look up or use another publication.

## 1. Decide what question is being asked

Pick the narrowest tool that answers it:

- **"How did issue X do?"**: `get_post_stats` for one issue, `get_post_stats_batch` for several.
- **"How did this theme do?"**: find the issues in the theme (`list_posts`, and the strategy doc for the theme), then `get_post_stats_batch` on them.
- **"Is this working overall?"**: `get_publication_stats` for active subscribers, engagement rates, growth, earnings and top acquisition sources. Use it for the big picture, not a single-post decision.
- **"What's the traffic like?"**: `get_website_analytics` for totals, `get_website_analytics_breakdown` for a ranked breakdown by dimension (page, source). Call `get_website_analytics_conditions_schema` before building a non-trivial `conditions` filter rather than guessing its shape.
- **An automated email sequence**: `get_automation_stats` (overall, per-email, per-step subscriber counts).
- **AI crawler traffic**: `get_crawler_analytics`. This is whether AI systems are indexing the content, not whether people read it. Don't mix it up with reader engagement.
- **Growth through others**: `get_referral_program` and `list_recommendations`.

Don't pull everything by default. Start from the question.

## 2. Compare like with like

A single number means little alone:

- Compare an issue with the publication's typical rates from `get_publication_stats`, and with other issues in the same theme.
- Look at the metric that fits the question: opens for subject line and timing, click-through for the content itself, unsubscribes and bounces for fit and list health.
- Note how many issues a conclusion rests on. One issue is an anecdote, not a pattern. Say so.

## 3. Report to the user

Lead with the answer, then the numbers behind it. Say where the evidence is thin. Propose options rather than decreeing: more of a theme, less, a different angle, or no change yet. The user decides the direction.

## 4. Record conclusions that change direction

When a number actually changes your mind or the user's about direction, write that conclusion into the relevant theme's content strategy doc: `read_file` the doc first so `edit_file` matches exactly. Record the conclusion and the evidence in a line or two, not the raw figures. A conclusion that isn't written down gets re-derived, or contradicted, next time.

## 5. Referral program

The referral program is read-only here. If the numbers suggest it needs a new milestone, a different reward, or to be turned on or off, that is a change request for the editor manager (`call_editor_manager_agent`, `flexibleWorkflow`), not something to act on directly. Agree the change with the user first.
