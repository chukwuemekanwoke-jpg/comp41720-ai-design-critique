# Collector validation and evaluation evidence

Owner: Sunmin Lee. Evidence reconciled on 21 November 2026.

## Provenance and frozen evaluation

The ten official ISD URLs came from the existing
[source manifest](../../data/sources_manifest_v1.json), with selection questions
in the [QA gate](../../data/qa_gate_10_v1.json). The
[16 November collection record](../collector-source-validation-2026-11-16.md)
records 10/10 successful fetches and nonempty immutable snapshots using
`main-text-v1`. This is a dated evidence capture, not a claim that the live pages
remain unchanged. The [snapshot ZIP](https://drive.google.com/file/d/18PpmXC95XouCgd_O0Z00hiYeTJ2quCrm/view)
contains the cleaned texts, compatible store and source/hash manifest.

The [880-request result bundle](https://drive.google.com/file/d/1Py9-3QnJpuPWjVKIwJDlSSkLRIlmc7rO/view)
contains raw responses, settings, frozen cases, Q004 retrieved passages and checksums.
It ran 44 cases 20 times each on 18 November, excluding two separate pending cases.

- Stack: `95fbc02d0577cbc79f10374ee8776c9990177a2c`.
- Harness: `072c3842a96fac7228ec43f8654588e2157b2304`.
- Dataset SHA-256: `50140557dc4e531f52cb50442a8ddd028e0e11097e62c23005aa32fc36b265ac`.
- Model: `llama3.2:3b`, digest `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`; Ollama `0.40.16`.
- Prompt `studentpath-answer-v1`, temperature 0, output cap 256, context 8192,
  timeout 20 seconds, `top_k=5`.

580/880 requests passed the automatic checks; this is **not answer accuracy**.
Expected-source hits were 23/25, but Q004's returned S004 passages did not contain
the correct graduate renewal context. There were 86 evidence-only fallbacks.
Nine of 44 cases varied in status, always involving fallback; this is not a
measurement of answer-text determinism. The suggested threshold failed to reject
all seven out-of-collection cases and is not a validated deployment threshold.
59 responses were flagged for personal eligibility/approval claims and require
Answer-owner review. This frozen stack predates later guard/resilience changes;
these figures must not be presented as results for the latest integrated build.

## Independent review of Emeka's recovery evidence

On 21 November, inspected the complete saved
[recovery JSON](https://drive.google.com/file/d/1aKymAYJeBbV6TRCauw7pwJTQLbrYfBzZ/view),
SHA-256 `2cd575f2148d942fee35fb7a052732f4c47a6ca1b157a9c0543d5d99f725a240`.
This was a review of Emeka's saved responses, not a new live run by Sunmin.

| Stage (19 November UTC) | Retrieval | Gateway |
| --- | --- | --- |
| Baseline, 14:24:08 | `idx-10`, S003 v1, no pending sources | `degraded`, v1 evidence retained, no abstention |
| Pending, 14:24:17 | `idx-10`, indexed S003 v1 versus latest v2 | `insufficient_evidence`, `pending_source_update`, both versions and detection time |
| Recovered, 14:24:25 | `idx-11`, S003 v2, no pending sources | `degraded`, v2 citations retained, no abstention |

Assertions checked that the pending response names S003 and versions 1/2 and
that the recovered Retrieval/Gateway identities agree on `idx-11` and S003 v2.
The baseline and recovered responses use **evidence-only fallback**, not generated
prose. These records support source-specific update refusal and evidence recovery;
they do not themselves contain Indexer process commands or broker restart logs.
Kezhen's [existing review](adr0003-evidence-review.md) separately documents the
10/10 pending-run checks and the unaffected S006/S007 evidence-only control.

## PR #33 independent integration checks

Reviewed head `708f0530f6908a3f45392395de6c22bb10ad945f` in an isolated Docker
project on 21 November; existing snapshot/evaluation stores were not modified.

- Full container suite with real RabbitMQ: **335 passed, 3 optional Ollama tests skipped**.
- Existing live product checks: **6/6 passed** (frontend assets, continuous pipeline,
  pinned versions, duplicate/quarantine handling, Gateway evidence and readiness).
- Independently observed `idx-1`/v1 → pending refusal → `idx-2`/v2 after Indexer
  restart, with seed preserving the changed page. `SEED_FORCE=1` restored fixture
  A as v3/`idx-3`, reusing the original snapshot. An unrelated source remained
  available in evidence-only mode during a further pending change.
- Real RabbitMQ refresh demo passed A,A,B,A versions 1,1,2,3 and replay of all
  three event IDs after a connection failure. Six OpenAPI documents validated.
- Separate opt-in Ollama run: **3/3 passed**, covering supported evidence,
  unrelated evidence and missing-model fallback. Then **2/2 actual Answer-container
  HTTP probes passed** through `host.docker.internal` with `llama3.2:3b` and the
  model settings above. These small synthetic checks establish integration,
  not immigration-answer quality.

Review evidence is recorded on [PR #33](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/33#pullrequestreview-6004501023)
and the [Ollama follow-up](https://github.com/chukwuemekanwoke-jpg/comp41720-ai-design-critique/pull/33#pullrequestreview-6004515645).
Local artifacts include pytest XML, product-check JSON, complete boundary/HTTP
responses, logs, image identity and dependency versions. Verification containers
were stopped with their disposable volumes retained. No merge was performed.

## Remaining scope

Q009's funds-only correction is confirmed by the evaluation owner; its removed
course-fee clause belonged to visa-required nationals, outside the question's
non-visa-required cohort. Q004 extraction/chunking remains a
[documented limitation](q004-chunking-limitation.md). Final quality claims need a
separately pinned integrated revision and reviewed answers; do not combine the
frozen 880-run counts with pending/recovery or later integration checks.
