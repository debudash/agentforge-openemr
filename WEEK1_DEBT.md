# Week 1 debt carried into Week 2

What the Week 1 Clinical Co-Pilot (submitted at `main`, `5c73a61`) left behind, how each debt showed
up once Week 2 built on it, and what closed it. Each item was confirmed against the Week 1 code, not
recalled. Commits are on `week2`.

## Fixed in Week 2

| # | Carried from Week 1 | How it showed up in Week 2 | Fixed | Commits |
|---|---|---|---|---|
| 1 | **The evals could not block anything.** They ran by hand, with no hook and no CI, and graded on a free judge that was rate-limited on most turns, so those verdicts were discarded as "not applicable". | A gate that a rate limit can silence is not a gate, and Week 2 makes CI a hard requirement. | Four of the five rubrics are deterministic and need no model. The gate runs in a pre-push hook and a GitLab CI job, and it was shown to refuse a deliberate regression (MR !3). | `dd1cfc8`, `349d642`, `fcbcf63` |
| 2 | **"Looked nothing up" was treated as off-topic.** Week 1 added that rule so an off-topic question could not re-emit an earlier answer. | It refused the questions the product exists for: "what changed" and "what should I pay attention to" failed 8 times in 9, with no tool called. | A turn that looked nothing up is told to look, with a forced tool call, before any verdict. | `c39529d`, `cc018ae` |
| 3 | **The same rule stood aside for a boundary statement.** | Routed to the guideline corpus, the model answered "what is the recommendation" with no search, said no guidelines were found "in the search results", and the turn was marked Complete. | Grounding rule 13: an evidence question's first round must call a tool; if no search ran, the answer shows no guidance, says so, and is partial. Gate cases S11 and S12. | `accf3b3` |
| 4 | **Production ran a different OpenEMR.** Railway ran the stock `openemr/openemr` 8.0.0 image while the code was written and tested on 8.1-dev and later 8.2.0-dev. | The Co-Pilot and Demo Data tabs worked locally and returned a blank 500 in production (`PatientSessionUtil::getPid()` does not exist in 8.0.0). The skew broke the deploy three times. | The module was made to read the patient in a way 8.0.0 understands. Then Railway moved to an image built from this repository, with a preflight of the module against the target. | `05cbb8c`, `5ade76a`, `5b986d8` |
| 5 | **Free models.** The agent and judge ran on free OpenRouter models. | Rate limits and outages decided results more often than the code did. | `gemini-2.5-flash-lite` for the agent and vision, `claude-sonnet-5` as judge, behind the existing provider allowlist. | `37a5c8a` |
| 6 | **Citations were record ids only.** | A document fact needs a page, a quote and a box to click through to. | Citation contract v2 adds the provenance fields; Week 1 ids still resolve unchanged. | `f7d961d`, `5f30861` |

## What the debts had in common

Items 2 and 3 are the same failure: a safety control that reported the wrong outcome rather than
letting anything through. A refusal fired on a valid question, and an absence was reported as
complete. Week 2's answer is in `W2_ARCHITECTURE.md` §12b: build the
refusal path as rigorously as the acceptance path, and give every refusal a gate case that asserts
what the clinician actually sees.
