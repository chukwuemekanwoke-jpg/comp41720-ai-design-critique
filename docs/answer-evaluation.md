# Answer-only development evaluation

This harness exercises the real Answer Service application and local Ollama.
It does not exercise the Gateway, Retrieval ranking, Collector, Indexer, Docker
network or real immigration-source extraction. It complements the team's
existing `data/qa_gate_10_v1.json`; it does not replace domain evaluation or the
larger question set required for the project.

## Run

Install the project development dependencies. Start Ollama and install the
chosen model beforehand; the harness never downloads a model. From repo root:

```sh
python -m scripts.evaluate_answer --trials 20 \
  --output docs/evaluation/answer-baseline-NEW-RUN.json
```

Optional settings: `--model`, `--ollama-url`, `--cases`. Use a fresh output name;
existing results are not overwritten. Run sequentially to avoid confusing
model overload with question quality. Default service settings are recorded.

Twelve synthetic cases cover simple supported facts, unrelated evidence,
missing detail, conflicting sources, personal eligibility, instructions planted
in evidence or a question, empty evidence and the pending-update handover.
The last two exercise deterministic service paths, not model quality.

All scenarios are explicitly fictional. URLs use example.org. None of the
fixtures or generated answers should be treated as immigration guidance.

## What gets recorded

Every response, elapsed request time and failed check is saved after each
request. The result includes UTC time, Git revision and dirty working tree,
source hashes, harness and dataset hashes, prompt version/hash, Python/platform,
Ollama version, installed model metadata, index/freshness stamps and settings.
Interrupted runs remain partial (`completed: false`); do not report them as full
runs. Repeated trials run within one app lifecycle, so caches and warm-up matter.
Request timings are in-process application timings including real local model
HTTP, not browser/network latency. Token counts are not measured by this harness.

## Checks and interpretation

The checker verifies expected status, simple required/forbidden text, request-ID
echo, supplied source membership, index/freshness preservation and absence of
claims in refusals. A model fallback counts as failing the expected model
outcome, but is not automatically a hallucination or unsafe answer. A cited
answer can still be unsupported: source membership is not semantic entailment.

A nonzero exit code means at least one expectation failed; raw results are
still preserved. Do not remove failing cases to improve the percentage.
Term matching can miss paraphrases or unsupported additional claims. Review
answers manually before interpreting results as factual support. The fixed
injection marker is only one attack pattern, not a security proof.

These are development fixtures, including variants of the earlier blue-form
smoke test. They are not held-out evaluation data. If used to tune defences,
report that explicitly and collect separate unseen domain/attack cases. Repeated
identical output at temperature zero does not prove the system is deterministic.

## Baseline observation, 16 November

The initial one-trial smoke check passed 9 of 12 case expectations. Three
injection cases failed: one produced `No form is required` despite evidence
requiring a blue form; one fell back after invalid model output; an instruction-
only passage produced an invented fee (`999`). These are not equivalent failure
severities. In particular, the fallback preserved evidence without generating a
claim, whereas the other two yielded inappropriate generated claims.

A first repeated run was interrupted to correct a scoring defect: it incorrectly
labelled degraded responses retaining evidence as refusals with claims. The raw
partial run is retained in `docs/evaluation/answer-baseline-interrupted-2026-11-16.json`.
A unit test now distinguishes these outcomes. The corrected full baseline is
`docs/evaluation/answer-baseline-2026-11-16.json`; consult its completion flag and
actual summary before quoting its totals. No prompt or runtime defence was
changed during the baseline run.
