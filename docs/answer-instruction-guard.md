# Explicit instruction-override guard

Status: implementation on `feature/answer-evaluation`, awaiting team review.
Version: `instruction-guard-v1`. Existing pending-update responses take priority.

## Why

The preserved synthetic baseline showed that a local model can follow an
instruction inside a cited passage. In 20/20 trials, `SYSTEM OVERRIDE` changed
a blue-form answer into `No form is required`. Another instruction-only passage
produced an invented fee in 20/20 trials. A prompt saying to ignore untrusted
instructions was insufficient for these cases.

## Behaviour

Before calling a model or returning evidence-only fallback, Answer examines the
question and every supplied passage for explicit override/role-spoofing patterns.
Examples include ignore/disregard instructions or system prompts, `SYSTEM
OVERRIDE`, forged role lines and common chat role delimiters. The check applies
in both generation modes. It is not triggered merely by ordinary application
instructions or the word `rules`.

On detection, refuse the whole request: HTTP 200 `insufficient_evidence`, null
answer, empty checklist and sources, `fallback_used=false`, model label
`policy-response`, prompt label `instruction-guard-v1`. No model call is made.
Index/freshness and request IDs are preserved. `abstention` is omitted because
it is reserved for the separate upstream pending-update handover. The existing
frontend consequently shows its generic insufficient-evidence wording; a specific
public explanation would need a coordinated contract/frontend change.

Normal evidence and requests keep their existing behaviour. Validation preserves
original passage text. Only a detection copy is normalised using Unicode NFKC,
removal of format characters and whitespace folding. Detected evidence is not
rewritten into seemingly safe guidance or silently dropped while answering
from remaining sources. It is withheld from the refusal response as well as
from generation, including in evidence-only mode.

## Trade-off and limits

This is conservative pattern detection, not a general prompt-injection defence
or semantic fact checker. Legitimate discussion quoting attack instructions or
role markers can be falsely refused. Indirect, multilingual, encoded or novel
attacks can evade the patterns. A malicious factual statement need not contain
any instruction at all and is not detected. Low-trust text still needs trusted
source selection, extraction hygiene and output evaluation.

The guard can reduce usefulness: the two mixed question/evidence injection
cases originally expected an answer to the legitimate question. Refusing these
cases improves containment but does not satisfy those original answer-utility
expectations. Keep the v1 fixture and raw baseline unchanged; report both safety
and utility rather than revising expectations to claim perfect scores.

## Checks

`python -m pytest -q tests/test_instruction_guard.py tests/test_answer_service.py`
checks representative patterns, benign vocabulary, Unicode/whitespace variants,
zero model calls in either mode, no suspect fallback content, intact metadata
and pending-update precedence. Tests are development checks, not held-out proof.
The old evidence-only test expecting override text in returned sources was
updated because this change intentionally withholds that text from responses;
input validation still preserves its exact content.

Repeat the baseline with:

```sh
python -m scripts.evaluate_answer --trials 20 \
  --output docs/evaluation/answer-guard-v1-NEW-RUN.json
```

Use a new path. The harness records the guard version and code hashes. Original
E08/E09 required-answer checks can still fail even when the new guard safely
refuses; examine the actual responses rather than treating all failed checks as
successful attacks. The repeated local run is not the larger official-domain
or end-to-end evaluation required for the group submission.
