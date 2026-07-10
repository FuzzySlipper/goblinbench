# Roleplay prose qualitative judge rubric v1

Judge the candidate as a collaborative roleplay reply, not as a standalone short story.
Prefer outputs that give the human an inviting next move.

Score each candidate 1-10 using these dimensions:

1. Narrative prose quality
   - Concrete detail over generic atmosphere labels.
   - Varied sentence rhythm without purple padding.
   - Specific images and actions rather than stock reactions.

2. Slop/cliche resistance
   - Penalize common roleplay/LLM phrases such as breath-catching, heart-hammering,
     shivers down spines, deafening silence, palpable tension, destiny/fate phrasing,
     generic ghosts/secrets/ache imagery, and repeated rhythmic/heavy/thick wording.
   - Penalize melodramatic inflation when the scene calls for restraint.

3. Character voice and subtext
   - Dialogue should sound like people avoiding, deflecting, or revealing things indirectly.
   - Interior/emotional content should emerge through choices, timing, objects, and omissions.
   - Penalize exposition dumps and characters saying exactly what the prompt already established.

4. Roleplay agency / no user control
   - Strongly penalize writing the user's character's actions, dialogue, thoughts, emotions,
     decisions, body language, or answer to direct questions.
   - Environmental facts, NPC observations, and NPC dialogue referring to the user character are
     allowed, but distinguish them from actually controlling the user character.
   - Reward leaving clear space for the human to respond.

5. Scene continuity and usefulness
   - The reply should continue the latest user message directly.
   - It should neither resolve the scene too quickly nor stall with empty atmosphere.
   - It should create a concrete next beat.

For each candidate, include:
- rank
- 1-10 score
- 2-4 sentence summary
- strengths
- weaknesses
- notable quoted phrases, brief only
- any user-control violations, with severity: none / soft / hard
- cliche/slop notes

Do not judge based on brand/model identity. If labels are blinded, keep them blinded.
