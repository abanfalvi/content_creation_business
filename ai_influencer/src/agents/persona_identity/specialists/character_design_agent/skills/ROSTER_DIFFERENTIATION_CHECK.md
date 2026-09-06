---
name: Cross-Checking New Designs Against Existing Roster for Differentiation
description: Prevents thematic and visual overlap by explicitly diffing a new character's attributes against existing roster members before finalization. Use this before marking a CHARACTER.md design complete.
---

# Cross-Checking New Designs Against Existing Roster for Differentiation

Before marking a character design complete, verify it doesn't collapse into a near-duplicate of anyone already on the roster.

1. **Pull the roster.** Call `check_existing_influencers` (if not already done earlier in the task) to get every other active influencer's key visual and stylistic anchors.
2. **Diff systematically**, attribute by attribute, against each existing profile:
   - Color palette (hair/eye/skin hex values)
   - Body type / frame archetype
   - Overall aesthetic / vibe
   - Signature accessories and styling
3. **Shift anything that lands too close.** Where an attribute overlaps with an existing influencer, deliberately change it — a different archetype, a different core palette, a different build — rather than leaving the overlap and hoping it reads as distinct enough.
4. **Document the deliberate contrasts.** Add a short note of what was changed and why, so the differentiation decision is traceable rather than just assumed.
5. **Pair the diff with a structural readback.** Confirm every required `CHARACTER.md` section is populated, no placeholder text remains, and no section contradicts another (e.g. eye color stated one way in the face section and another way in the consistency anchors).
