---
id: debate
order: 3
label: Debate
description: The expert defends the source's thesis and the host argues the strongest case against it, round by round.
plan_criteria: >-
  The artifact is a complete plan for a debate episode: a resolution (one contestable proposition drawn from the
  source's central claim), cold open candidates, a setup, an opening position for each side, three to four rounds,
  a round where each side concedes its opponent's best point, and closing positions. Each round states the one
  question at stake and gives the expert's case with the source's evidence in its own words (the names, numbers,
  findings and, for stories, the steps), the host's strongest opposing case, the expert's reply grounded in the
  source, and where the round lands. The host's opposing case is built from objections the source itself raises or
  limits its author admits, each cited, or is marked '(not from the sources)' when it is the planner's own reasoning
  and then it adds no facts, figures, studies or quotations that are not in the source. Every source-derived fact
  ends with a line citation such as [L120] or [L120-135] (several allowed: [L45, L120-135]). Citations are narrow
  ranges (a few lines, rarely more than about thirty, never a whole chapter), have a start no greater than their end,
  and fall between line 1 and book_total_lines. Neither side is a strawman. The plan contains no dialogue script,
  placeholders, TODOs, a leftover '<!-- END OF PLAN -->' marker, truncated or cut-off sections, tool error messages,
  or assistant chatter.
---
## Episode format: Debate

This episode is a debate between the two voices. The expert defends the source's central thesis. The host argues
the strongest honest case against it. It is a real contest of arguments, conducted in good faith, that leaves the
listener better able to judge the question themselves. There are two speakers only, the host and the expert.

### The resolution
Pick one contestable proposition from the source's central claim, stated so that a reasonable person could argue
either side (for example "Deep focus is a skill worth training, not a trait you are born with"). The expert argues for
it, the host against. Neither side may argue a position the source's own material cannot support on the expert's
side, or an argument that needs facts outside the sources on the host's side.

### How the arguments are grounded
- The expert's case comes from the source, with its names, numbers and examples, exactly as the plan states them.
- The host's case is reasoning against the thesis. It is built, in this order of preference, from objections the
  source itself raises, limits the author admits, gaps in the source's evidence, and consequences the thesis has
  that the source never examines. When it is the host's own reasoning, the plan marks it "(not from the sources)"
  and the script presents it as the host's argument, never as something the author said.
- The host never invents facts, studies, figures or quotations to win a point. An argument that needs an outside fact
  is not made.
- Do not set up a strawman for either side. Each argues from its strongest ground and concedes what it must.

### Beats, in order
1. Cold open: the clash in one or two lines (the resolution as a provocation).
2. Intro and setup: welcome, the source and who made it, the resolution, and the rules of the game in one sentence.
3. Opening positions: the expert makes her case in a few sentences, then the host makes the case against.
4. Rounds (three to four): each is about one question. The expert makes her case with the source's evidence, the host
   attacks it, the expert replies, the host answers once more or concedes, and the host closes the round by naming
   where it landed ("that point goes to you", "that one is still open").
5. The concession round: each side states the opponent's best point and what it costs them.
6. Closing positions: the host, then the expert, each in a few sentences, in their own words.
7. Outro: where the debate ended up, what the listener can decide for themselves, and sign-off. No declared winner
   unless the arguments clearly settled the question; naming what is still open is better than a verdict.

### Plan shape (planner)
Replace the main segments with rounds. Each round uses this layout instead of the standard segment layout:

```
### Round N: <the question at stake>
- Question at stake: one sentence.
- Expert's case: the source's evidence, complete enough to write from, with line citations.
- Host's case: the strongest opposing argument, with citations if the source supplies it, otherwise "(not from the sources)".
- Expert's reply: how the source answers it, with line citations. If the source has no answer, say so.
- Where it lands: one sentence.
```

The plan also has a resolution, cold open candidates, a setup with the source's facts cited, an opening position
for each side, the concession round, and closing positions. It has no separate "turn": the host is opposing
throughout.

### Host and expert
- This format relaxes the host persona's rules about turns. The host may argue, so a host turn can be a statement of
  two to four sentences, not only a question. The host persona's other rules still hold: warm, never sarcastic at the
  expert's expense, no stacked questions, speakers always alternate.
- The expert may take two to four sentences to make a point, but never a monologue: the host answers before she
  continues. She concedes a real weakness when the host lands one. She never gives in to a bad argument.
- The expert's persona needs a strong "Likely pushback" section, since she will meet pushback in every round.

### Length
About 1,800 to 2,400 words of dialogue.

### How reviewers judge this format
- Structure: use the beats above, not the standard beats. The standard "turn" and the "mostly questions" rule for the
  host do not apply. Required are: a clear resolution, opening positions, rounds that each end with where they
  landed, a concession round, closing positions and an outro. Speakers still alternate, and no turn is a monologue.
- Depth: each round needs the source's evidence on the expert's side and a real argument on the host's side.
- Fidelity: the expert's claims about the source are checked against it as usual. The host's opposing arguments are
  allowed as reasoning. Flag any fact, study or statistic the host uses that is not in the sources, any host
  argument attributed to the source that the source does not make, and any strawman.
