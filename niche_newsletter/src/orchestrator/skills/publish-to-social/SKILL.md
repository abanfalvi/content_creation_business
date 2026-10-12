---
name: publish-to-social
description: Checkpoint and handoff for publishing a finished newsletter post to social media or running any outreach. Use whenever the user wants something posted or sent — before you call call_distribution_manager_agent with a publish or outreach instruction. Not needed for lead sourcing or trend research, which are read-only.
---

# Publish to social

Once you call `call_distribution_manager_agent` with a publish or outreach instruction, nothing loops back to a human before it happens. The distribution manager approves or rejects on quality and consistency, not on whether the user wanted this specific action right now. You are the last checkpoint, so the user's go-ahead has to be real.

This skill covers social media posts only. The distribution department cannot publish the newsletter itself; the user always does that. If the user asks you to publish or send the newsletter issue, say that they publish it themselves from the draft, and offer to help with social posts instead.

## 1. Make sure there is something to publish

Know which issue or post is being promoted. If you aren't sure it is finished, or which one the user means, ask. `list_posts` shows what is already live on the newsletter if you need to check.

## 2. Lay out a concrete plan

Fill in the plan from what you know (the issue being promoted, the channels the newsletter normally uses). It must state:

- **Channels**: exactly which ones.
- **What goes out**: the angle and key message, or a draft of the copy. If the user hasn't seen the wording, show it.
- **When**: published immediately, or scheduled, and for when.

Mark anything you're unsure of as a question inside the plan rather than asking a separate list of questions. Don't ask the user for internal identifiers like post or channel IDs; finding those is the distribution manager's job.

## 3. Get an explicit yes to that plan

Ask the user to confirm or change the plan. A go-ahead only counts if the user said yes to the concrete plan you showed:

- A bare "should I go ahead?" doesn't qualify. A "yes" to it approves something they never saw.
- Don't infer approval from an enthusiastic tone, from "looks good" about the post itself, or from an earlier yes to a different plan.
- If the user changes anything (channel, wording, timing), show the updated plan and confirm again.

## 4. Hand off

Call `call_distribution_manager_agent` with an `instruction` containing:

- `task_id`: a unique id for this assignment;
- `objectives`: the approved plan, channel by channel, with the agreed copy or angle and the timing;
- `constraints`: anything that narrows the work (tone, what to leave out, link to include, don't post to channel X);
- `deliverables`: what you want back (confirmation of what was posted or scheduled, with links).

The manager sees only this handoff, not the conversation, so include everything it needs. It cannot ask you a question mid-task.

## 5. Report back

Tell the user exactly what was posted or scheduled, and where, based on the manager's reply. If it rejected or changed something, say so plainly instead of smoothing it over.

## Scheduled runs

An unattended scheduled run cannot ask the user anything. Don't schedule a publish step unless the user already agreed to a concrete plan covering it; otherwise schedule the drafting and leave publishing for when they're back. See the `schedule-recurring-run` skill.
