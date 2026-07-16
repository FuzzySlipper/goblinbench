# Roleplay prose qualitative benchmark pattern — 2026-07-07

## Context

Patch wanted a cheap way to test long-form roleplay/chat prose quality outside SillyTavern. SillyTavern itself is too byzantine and provider-setup-heavy to be a useful benchmark harness. The useful path is to model the core interaction directly as GoblinBench plain-chat scenarios and emit side-by-side Markdown artifacts for humans to inspect.

Initial metric: bare narrative prose quality / anti-slop resistance for SFW collaborative storytelling replies.

## Scenario shape

Use a `roleplay-prose` suite with plain `OpenAiModel` candidates and `OpenAiChatRunner`.

Good first-pass prompts:

- SFW collaborative RP continuation.
- “Write only the next assistant roleplay reply, not a full story and not analysis.”
- 500–750 words, long enough to show prose habits without generating huge transcripts.
- One viewpoint constraint: first person or third person limited.
- Specific scene pressure + latest user message.
- No headings, bullets, OOC notes, analysis, or meta commentary.

Three starter scenario types that surfaced useful signal:

1. **Quiet sensory/interiority:** exhausted traveler at rainy inn door with a sealed letter; tests atmosphere, restraint, and interiority.
2. **Dialogue/subtext:** betrayed partners on foggy train platform; tests natural dialogue, subtext, and avoiding exposition dumps.
3. **Action/spatial tension:** maintenance tech in orbital duct on comms with ex; tests legible action, spatial clarity, and relationship tension through timing.

## Cheap deterministic-ish scoring

Use `latency` + `heuristic-text` only. The score is not the result; it catches obvious cliche/slop markers and harness failures.

Useful forbidden markers for roleplay prose:

- physical-reaction slop: `shiver down`, `spine`, `heart skipped`, `heart hammer`, `breath hitching`, `breath she/he/I didn't know`, `eyes widening`, `voice barely above a whisper`
- atmosphere slop: `the air was thick with`, `palpable tension`, `silence was deafening`, `heavy with tension`, `electric`
- melodrama/metafate: `little did`, `destiny`, `fate had other plans`, `for what felt like an eternity`, `as if on cue`
- stock RP gesture language: `couldn't help but`, `without realizing it`, `met his/her gaze`, `smirked`, `chuckled darkly`
- high-level abstract gothic filler if not scene-earned: `ghost`, `ache`, `precipice`, `secrets buried`

Keep required markers sparse, usually the viewpoint character and one scene anchor, so the heuristic scorer does not become keyword stuffing.

## Prompt variants

A v0 prompt with normal style guidance surfaced Gemma 4’s default melodramatic habits well. A v1 anti-slop variant reduced cliche hits sharply.

Effective v1 addendum:

```text
Additional style constraints for this variant:
- Prefer plain, specific prose over dramatic intensity.
- Do not use stock physical reactions (spine shivers, breath catching, heart hammering, eyes widening).
- Do not write phrases shaped like “not a cleansing thing; it was...” or “the silence was...”.
- Avoid abstract atmosphere labels such as palpable, thick, electric, heavy with tension, destiny, fate, ghosts, ache, precipice, or secrets buried.
- Let emotion appear through small choices, timing, objects, and what the character refuses to say.
- Keep sentences varied; leave some lines quiet.
```

Observed effect on local Lemonade Gemma-4-26B-A4B-it-GGUF:

| variant | cliche-ish hits across three scenarios |
|---|---:|
| v0 | 15 total |
| v1 | 4 total |

Qualitatively, v1 also made outputs more grounded, though still not free of stock phrasing.

## Local Lemonade Gemma 4 26B quirks

Endpoint/model:

```text
http://192.168.1.23:13305/v1
Gemma-4-26B-A4B-it-GGUF
```

Gemma 4 via Lemonade/llama.cpp may emit empty assistant `content` and put everything in `reasoning_content` unless thinking mode is disabled at the chat-template layer.

Working request knob:

```json
{
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

GoblinBench `OpenAiChatRunner` now supports candidate `config.request_overrides` for these top-level provider/model-specific request fields. Candidate config pattern:

```json
{
  "id": "lemonade-gemma4-26b-roleplay",
  "name": "Lemonade Gemma 4 26B A4B roleplay prose",
  "kind": "OpenAiModel",
  "model": "Gemma-4-26B-A4B-it-GGUF",
  "provider": "lemonade",
  "base_url": "http://192.168.1.23:13305/v1",
  "system_prompt": "You write immersive collaborative roleplay replies. Stay in-scene. Do not explain the task, summarize the prompt, apologize, add safety disclaimers, or address the user. Write polished narrative prose with natural dialogue and concrete sensory detail.",
  "config": {
    "temperature": 0.85,
    "max_tokens": 2200,
    "request_overrides": {
      "chat_template_kwargs": {
        "enable_thinking": false
      }
    }
  }
}
```

## Reporting path

After runs land in the canonical store, use `gb-qual-report.py`:

```bash
python3 scripts/gb-qual-report.py \
  --runs <run-id-or-comma-list> \
  --suite roleplay-prose \
  --no-judge \
  --campaign roleplay-prose-gemma4-26b-v0-v1 \
  --out runs/qualitative/roleplay-prose-gemma4-26b-v0-v1/qualitative-report.md
```

`gb-qual-report.py` was updated to extract the human-facing assistant `message.content` from OpenAI-compatible `output.json` envelopes and include full candidate outputs in `<details>` blocks. This matters for roleplay users: they need the actual prose, not just excerpts.

## Next useful benchmark dimensions

Once bare prose quality is in the ballpark, add separate scenario families rather than one huge transcript:

- **Instruction following in RP:** preserve POV, tense, character boundaries, and do not control the user’s character.
- **Continuity over turns:** feed a compact 3–5 turn transcript and test whether the model preserves established facts without over-recapping.
- **Dialogue/subtext:** characters should not say exactly what they mean; penalize exposition dumps.
- **Pacing:** continue a scene without prematurely resolving it or escalating every beat.
- **User handoff quality:** does the reply give the human a clear next move without railroading?
- **Taste/style fit:** likely requires human preference review; use LLM judge only as commentary, not ground truth.
