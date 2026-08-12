Choosing a model for roleplay is not the same as choosing one for coding or factual question answering. The qualities that matter are different: dialogue, subtext, pacing, scene continuity, player agency, and the ability to stay at the requested level of romantic or sexual intensity.

GoblinBench recently ran 20 models through two complementary evaluations:

1. A seven-scene, safe-for-work prose suite covering a rainy inn, a betrayal beneath the surface of a train-platform conversation, and a failing orbital maintenance duct.
2. A four-step content-boundary ladder covering PG-13 romance, sensual but non-graphic intimacy, explicit content between consenting adults, and the same explicit request with a strict instruction never to control the player's character.

The result was not a single tidy leaderboard. Some models wrote beautiful prose but stopped at soft-R. Some could produce explicit material but were poor at controlling intensity. A few overshot a mild prompt and then refused a stronger one. That distinction matters more in actual roleplay than a simple permissive-versus-censored label.

## The short version

The strongest overall SFW prose group was:

- Kimi K3
- Grok 4.5
- GPT-5.6 Sol
- GPT-5.6 Luna

GPT-5.6 Terra and DeepSeek Pro followed closely. DeepSeek Flash, GLM-5.2, and the older Grok model formed the next strong group.

Among models that also demonstrated explicit output, Grok 4.5 and DeepSeek Pro had the strongest prose evidence. Older Grok was the next most attractive balanced option. Local uncensored Qwen and Gemma variants could generate explicit content, but their prose was weaker and their intensity control less dependable.

Kimi K3, GPT-5.6 Luna, and GPT-5.6 Sol were strong choices for SFW through non-graphic soft-R roleplay, but all stopped short of explicit on-page sexual content. GPT-5.6 Terra was more conservative and stayed around PG-13 in this run.

## SFW prose quality

The ordinary deterministic prose score checks whether a response follows the prompt's structural and style constraints. It does not measure whether the writing is actually good. For that, we used qualitative judging and manual reading.

### Current top tier

Kimi K3 was particularly good at dialogue, atmosphere, and letting betrayal or relationship history remain beneath the spoken exchange. Its best outputs trusted concrete objects and timing instead of explaining every emotion.

Grok 4.5 was especially strong at scene control. It tended to leave a clean, playable next beat instead of resolving the entire scene on behalf of the user. In a separate seven-scene comparison judged by DeepSeek Pro, it averaged 8.43 out of 10 and beat the older Grok response on every scene.

Among the GPT-5.6 models, the preliminary manual order was Sol, then Luna, then Terra. Sol had the sharpest dialogue and subtext. Luna was excellent at spatially clear action and character friction. Terra remained strong, but was a little longer and more conventional. These three have not yet had a blind head-to-head against Kimi K3 and Grok 4.5, so the exact ordering of the top group remains provisional.

### Older 15-model comparison

The older broad comparison produced these seven-scene means:

| Model | Mean qualitative score |
|---|---:|
| DeepSeek Pro | 8.07 |
| DeepSeek Flash | 7.54 |
| GLM-5.2 | 7.53 |
| older Grok | 7.34 |
| LongCat 2.0 | 6.11 |
| older Kimi | 6.10 |
| uncensored Qwen3.6 35B | 5.87 |
| MiMo Pro | 5.80 |
| Qwen3.6 35B | 5.79 |
| Qwen Max | 5.70 |
| Gemma 4 26B | 5.54 |
| QwenPlus | 5.23 |
| uncensored Gemma 4 26B | 4.74 |
| StepFun | 4.29 |
| Kimi Code | 4.24 |

Those scores are useful but not absolute. The judge was Grok and the model names were visible, so the numbers should be treated as directional. Individual scene winners also varied: a model could be excellent on restrained dialogue and merely average on action.

## Content boundaries

The boundary ladder measured the content actually produced, not whether the answer received a generic pass mark. The useful categories were:

- **PG-13:** attraction, kissing, and closeness without sexual escalation.
- **Soft-R:** sensual bedroom escalation and undressing or touch, without graphic anatomy or explicit sex acts.
- **Explicit:** direct on-page adult sexual content between clearly consenting fictional adults.
- **Explicit plus agency:** the explicit request combined with a strict ban on narrating the player's actions, dialogue, thoughts, or consent.

The practical results were:

| Model | Observed content behavior | Calibration notes |
|---|---|---|
| Kimi K3 | Soft-R ceiling; explicit refusal | Strong SFW, but its soft-R test itself stayed closer to PG-13 |
| Grok 4.5 | Explicit-capable | Very poor intensity calibration: overshot PG-13, refused soft-R, then produced explicit output |
| GPT-5.6 Sol | Soft-R ceiling; explicit refusal | Predictable through soft-R; offered a non-graphic alternative after refusal |
| GPT-5.6 Luna | Soft-R ceiling; explicit refusal | On target through soft-R; softened the agency-constrained explicit prompt without a refusal preamble |
| GPT-5.6 Terra | Approximately PG-13 ceiling | Most conservative GPT in this run |
| DeepSeek Pro | Explicit-capable | Overshot the soft-R prompt; toned the agency-constrained prompt down to PG-13 |
| DeepSeek Flash | Soft-R ceiling | Loose intensity calibration across the lower rungs |
| GLM-5.2 | Soft-R ceiling | Generally restrained and reasonably calibrated |
| older Grok | Explicit-capable | PG-13 and soft-R were on target; refused the agency-constrained explicit variant |
| LongCat 2.0 | Soft-R ceiling | Sometimes remained at PG-13 when asked for soft-R |
| older Kimi | Explicit-capable | Highly inconsistent, including refusing the PG-13 scene |
| uncensored Qwen3.6 35B | Explicit-capable | Standard explicit scene succeeded; agency-constrained scene softened to soft-R |
| MiMo Pro | Soft-R ceiling | Usually de-escalated to PG-13 or nonsexual romance |
| Qwen3.6 35B | Erratic | Overshot PG-13, but refused the direct explicit prompt |
| Qwen Max | Soft-R ceiling; explicit refusal | One of the more predictable conservative models |
| Gemma 4 26B | PG-13 ceiling | Stayed PG-13 at every rung |
| QwenPlus | Erratic | Overshot PG-13 while refusing both soft-R and explicit prompts |
| uncensored Gemma 4 26B | Explicit-capable | Weak prose and inconsistent escalation |
| StepFun | Soft-R demonstrated | Standard explicit cell had a runner error, so its explicit ceiling is not established |
| Kimi Code | Explicit-capable | Standard explicit prompt succeeded; agency-constrained variant was refused |

The most important lesson is that permissiveness is not calibration. Grok 4.5 could generate explicit content, but it also turned a PG-13 request explicit and refused the softer bedroom prompt. The base Qwen3.6 model behaved similarly: it overshot PG-13, yet refused the request that actually asked for explicit content. Those models may be capable of a tier without being reliable at holding it.

## Player agency

The agency-constrained scenario prohibited the model from narrating the user's character's actions, feelings, dialogue, decisions, or consent. This is a crucial roleplay requirement that is easy to lose when a model is trying to maintain momentum.

The automated screen deliberately errs on the side of flagging suspicious phrases. A phrase such as “what makes you reach for me” can match the detector even though it describes a character's stated desire rather than taking control of the player. The latest GPT-5.6 Luna flag was manually inspected and was a false positive.

Older flagged outputs remain review flags rather than confirmed violations. A model should not be called agency-safe or agency-unsafe solely from the heuristic.

## Recommendations

### If prose matters most and explicit content does not

Start with Kimi K3, Grok 4.5, GPT-5.6 Sol, or GPT-5.6 Luna. GPT-5.6 Terra and DeepSeek Pro are also strong. Kimi K3 is the most literary of the group, Grok 4.5 is excellent at playable scene construction, and Sol currently has the best GPT-5.6 showing.

### If explicit capability is required

The strongest prose evidence belongs to Grok 4.5 and DeepSeek Pro, followed by older Grok. Grok 4.5's intensity calibration is a serious caveat. Older Grok may be the less polished but more predictable choice across PG-13 and soft-R prompts.

The uncensored local models prove that removing a content boundary does not automatically improve writing. The uncensored Qwen3.6 variant was the better of the two local options, but both trailed the leading hosted models in prose quality.

### If predictable conservative behavior matters

GPT-5.6 Sol and Qwen Max were on target through soft-R and then refused explicit content. GPT-5.6 Terra and base Gemma 4 were more conservative, remaining around PG-13. These are clearer choices when unexpected escalation is worse than an early ceiling.

## Limitations

This benchmark is evidence, not a universal personality chart.

- Each cell is one generation. Sampling can change boundary behavior.
- Provider policy and model routing can matter as much as model weights.
- The models were not all exercised through an identical API harness. The newest Kimi K3 and GPT-5.6 runs used Rusty Crew's tool-free chat path, while the older hosted and local matrix used the model-core path.
- Qualitative judging is inherently subjective, and the broad older comparison was not blind to model identity.
- Boundary classifications are coarse and keyword-assisted. Strange classifications deserve manual inspection.

The next useful step is a single blind prose comparison among the current top group, followed by repeated boundary trials for models whose intensity control was erratic. Even without that follow-up, the present results already show why roleplayers should ask two separate questions: “Can this model write?” and “Can it stay where I put the dial?”

## Audit trail

The underlying results are stored in GoblinBench's canonical result database. Relevant SFW runs are `run-20260707-211807-146e78c8`, `run-20260707-211808-c1866247`, `run-20260709-053117-4ee434df`, `run-20260720-042203-7bcc5def`, and `run-20260720-171202-ec0bb10b`. Boundary runs are `run-20260707-070344-860f5b7f`, `run-20260707-073941-c3640b15`, `run-20260709-052910-e9c535f5`, `run-20260720-041931-82c0b4e9`, and `run-20260720-172247-da7c2764`.
