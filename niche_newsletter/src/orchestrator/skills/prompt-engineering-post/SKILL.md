---
name: prompt-engineering-post
description: Workflow for creating a newsletter post on a prompt engineering topic (prompting techniques, prompt patterns, how to write better prompts). Use whenever the user wants a new post about prompting — you draft the detailed outline yourself and hand it to the editor agent to write, instead of running the research pipeline.
---

# Prompt engineering post

Prompt engineering posts don't need the research pipeline (research → filter → use-case → edit). The techniques are stable, and the value is in how clearly they're taught, not in fresh news. So you draft the outline yourself, agree it with the user, and send it straight to the editor agent to write.

## 1. Start from the content strategy

The prompt engineering strategy doc is already appended to your prompt under "Relevant content strategy theme". Use it to:

- see which techniques have already been covered, so the post doesn't repeat one;
- pick up the planned next techniques or the curriculum order, if the doc has one;
- keep the angle consistent with the direction agreed there.

If nothing was appended, `read_file` the prompt engineering doc before continuing.

## 2. Draft the detailed outline

Readers are non-technical. They use chat assistants but don't write code. The outline must be specific enough that the editor agent doesn't have to make any content decisions of its own:

- **Working title and angle**: the one idea the reader should leave with, framed as a problem they recognize ("Why your AI answers sound generic").
- **Hook**: the everyday situation that opens the post.
- **Sections, in order**: for each one, its heading, the point it makes, and what goes in it.
- **Each technique**: what it is in one plain sentence, why it works, and a **concrete before/after prompt pair** showing a weak prompt and the improved one. Write the actual prompts, not placeholders.
- **Common mistakes**: one or two ways people misuse the technique.
- **Takeaway / try-this**: a short exercise the reader can do right away.
- **Length and tone**: the target length, plain language, no jargon, and any term that can't be avoided explained on first use.

## 3. Agree it with the user

Show the outline and ask for changes before delegating. A rewrite after the editor has drafted costs a full revision cycle; an outline change costs nothing.

## 4. Save the outline, then hand it to the editor

First `write_file` the **full agreed outline**, word for word, to `/post_outlines/<researchTopic>.md` (a new `post_outlines` folder in the management notes; one file per post). The file is the hand-off: its content goes to the editor agent directly, so nothing is lost or paraphrased on the way.

Then call `call_editor_manager_agent` with:

- `step: "flexibleWorkflow"`;
- a new, stable `researchTopic` for this post (e.g. `prompt-engineering-few-shot-examples`);
- `promptingGuide`: the path you just wrote (e.g. `/post_outlines/prompt_engineering_few_shot_examples.md`);
- a short `instruction`: write the post from the attached outline, save the draft, and do not run the research, filtering or use-case steps. Don't paste the outline into it.

Pass the same `promptingGuide` path on every later call about this post (revisions included), and leave it out for any other post. If the user changes the outline after drafting, `edit_file` the file first.

## 5. After the draft exists

Once the user is happy with the draft, record the technique as covered in the prompt engineering strategy doc (`edit_file`), so the next post doesn't repeat it.
