---
name: trend-research
description: How to research what is currently trending or timely while shaping strategy with the user — web trends plus TikTok and Instagram reels via the distribution manager. Use when the user asks what's trending or popular in the niche, or when deciding what to cover next and external signals would help. This is for strategy, not for researching the newsletter post itself.
---

# Trend research

This is research to decide **what to cover**, not the newsletter's own research. Once a topic is worth a full issue, the editor manager's research agent does the deeper job: don't do that here.

Trend signals are one input. Weigh them against how past coverage of the theme actually performed for this publication's readers, not only against what is popular elsewhere.

## 1. Check what you already know

Start from the relevant content strategy theme if it was appended to your prompt (coverage so far, planned direction), and from anything already gathered in this conversation. If trend research has already been run on this angle in this conversation, reuse its findings instead of repeating it: searches and transcriptions cost money.

## 2. Web trends

Use `web_search`, and `extract_web_content` for a specific page worth reading, to see what is timely in the niche. Keep it to what helps the strategy conversation; this is not source-gathering for a post.

## 3. Social trends (TikTok and Instagram reels)

Delegate to `call_distribution_manager_agent`. It can search by keyword or hashtag and transcribe the top videos. This is read-only: nobody is contacted and nothing is posted, so no user go-ahead is needed.

Write the `instruction` with:

- `task_id`: a unique id;
- `objectives`: which platform(s) (TikTok, Instagram, or both), the niche angle, and any keywords or hashtags worth trying;
- `constraints`: keep it focused. State how many videos to transcribe, since each search and transcription costs money;
- `deliverables`: what you want to learn (topics people respond to, hooks, formats), plus example videos with their numbers.

The findings come back only in the manager's reply, so relay what matters to the user. Don't paste the raw reply.

## 4. Weigh the signals

Before recommending more (or less) of a theme, check how past coverage of it actually performed: `list_posts`, then `get_post_stats` or `get_post_stats_batch` for the relevant issues. A topic that is trending externally but has underperformed for this publication's readers is a worse bet than the reverse. Present both sides to the user and propose options. Don't pick the topic for them.

## 5. Record what changed the direction

If the findings change the direction you and the user settle on, write that into the relevant content strategy doc: read it first, then `edit_file`. Don't record raw trend lists, only the conclusion and the reason, so the next conversation doesn't re-derive it or contradict it.
