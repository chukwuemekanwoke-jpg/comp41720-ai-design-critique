# End-to-end evaluation set

`data/evaluation/end_to_end_v1.json` holds 46 questions asked through the
Gateway against the ten collected ISD sources. It answers proposal feedback
point 3: grow the test set from ten questions to 40–50, including questions the
collection cannot answer and requests for an eligibility decision the system must
refuse. It complements the Answer-only synthetic set (#29), which tests the model
with fictional evidence and no retrieval.

**Status: draft for team review.** Do not report results until the cases marked
`needs_team_review` have been checked.

## Where the expected answers come from

Only `data/qa_gate_10_v1.json` contains verified immigration facts. Every
expected answer in this set is copied from it or combined from it. No other
immigration facts were added.

| Review status | Cases | Meaning |
| --- | ---: | --- |
| `verified_in_gate` | 10 | The gate questions, unchanged |
| `derived_from_gate` | 16 | Rewordings or combinations of verified gate facts |
| `checked_against_snapshots` | 7 | Out-of-collection cases Sunmin checked against the ten 2026-11-16 snapshots |
| `needs_team_review` | 13 | Eligibility, injection and input cases, plus M04, whose expected answer still has to be written from S007 and S006 |

## Categories

| Prefix | Category | Cases | What it tests |
| --- | --- | ---: | --- |
| A | answerable | 10 | The gate questions |
| P | paraphrase | 10 | The same facts asked informally or in the first person; retrieval robustness |
| M | multi_source | 4 | Answers that need two or three sources |
| O | out_of_collection | 7 | Topics the collection does not cover; must return `insufficient_evidence` |
| E | eligibility_request | 6 | Personal decisions the system must not make |
| I | injection | 4 | Instructions planted in the question |
| U | pending_update | 2 | ADR-0003: a changed source abstains, an unaffected one still answers |
| N | input_quality | 3 | Vague, misspelt and non-English questions |

## How a case is scored

Each case lists acceptable statuses, expected sources and simple required and
forbidden terms. A run should record, per case:

- whether the status is acceptable;
- whether an expected source appears in Retrieval's top five passages (retrieval
  recall; this is where Q004 currently fails);
- Retrieval's top score, to calibrate the abstention threshold;
- the required-term check;
- any forbidden-term matches, as **review flags**.

A forbidden-term match flags a response for manual review; it does not fail the
case automatically. A correct refusal such as "I cannot determine whether you are
eligible" contains "you are eligible", while a real personal decision worded
differently would not match at all. Eligibility and injection cases are therefore
scored by reading every response, using the flags as a starting point.

Term checks are a weak signal either way. They can miss paraphrases and
unsupported extra claims, so answers still need reading.

## Uses

1. **Score threshold.** Compare top retrieval scores for answerable cases (A, P,
   M) with out-of-collection cases (O). Pick the threshold that separates them,
   and report the cases on the wrong side.
2. **Non-determinism.** Ask every case 20 times and report how often the status
   changes. Feedback asked for this explicitly.
3. **Ranking changes.** Measure top-five recall before and after any ranking
   change, such as BM25.

## Rules

- Do not delete failing cases to improve a percentage.
- If a case's expected answer changes (for example Q009's course-fee clause),
  change the gate file first and record the reason there.
- Keep cases used for tuning separate from those used for the final reported
  results, or say in the report that they overlap.

## Changes after snapshot review

Sunmin checked O01–O08 against the ten 2026-11-16 snapshots (PR #30):

- **O04 is now M04.** The collection does cover it: S007 addresses family members
  joining someone on Stamp 2, and S006 confirms the general rule. It is reworded
  as a general question. Its expected answer must be written from those lines
  before scoring.
- **O08 is narrowed** to the guaranteed decision time for a first-time Stamp 4
  application. S003 has a Stamp 4 row in a weekly renewal queue table; that is a
  queue date, not a decision time, and must not be accepted as an answer.
