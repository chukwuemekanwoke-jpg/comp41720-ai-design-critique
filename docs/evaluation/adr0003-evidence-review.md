# ADR-0003 saved-evidence review — 2026-11-20

Reviewer: Kezhen Zhang, with AI assistance.

## Source records

Read the original JSON previews in the Google shared drive **COMP41720 - Group
17** after UCD sign-in:

- `end-to-end-pending-2026-11-19.json`
- `end-to-end-pending-recovery-2026-11-19.json`

These are team-produced saved responses inspected on 20 November, not a new live
run performed by the reviewer. No shared file was changed.

## Pending run

The first record ran U01 and U02 five times each on 19 November, beginning at
13:50:29 UTC. It records clean Git revision
`072c3842a96fac7228ec43f8654588e2157b2304`, dataset SHA-256
`eb79345e4285d664eb0dac4c1f75138d8098076723140433a6f35840273dd25b`, and harness
SHA-256 `7acbe07bf0de726a85e15e8c44086f99ad05e290a8054fd913305f4d7ba8ce72`.
The report is completed, with 10 requests and 10 automatic check passes.

| Case | Evidence state | Gateway result in all five trials |
| --- | --- | --- |
| U01, affected renewal question | `idx-10`; S003 indexed v1, Collector v2; freshness confirmed | `insufficient_evidence`; `abstention.reason=pending_source_update`; S003 named with both versions and detection time |
| U02, unaffected student question | `idx-10`; S006/S007 evidence; no pending sources; freshness confirmed | `degraded`; evidence sources retained; `abstention=null`; evidence-only fallback |

The control demonstrates that an unrelated source update does not trigger a
global refusal. It does not demonstrate a generated answer: the control's
`answer` is null and its model is `evidence-only`.

## Three-stage recovery record

The second record asks the same affected renewal question at three stages on
19 November:

| Stage / capture time UTC | Collection / S003 version | Retrieval pending | Gateway status |
| --- | --- | --- | --- |
| Baseline, 14:24:08.191290 | `idx-10` / v1 | Empty | `degraded`, evidence retained, no abstention |
| Pending, 14:24:17.626035 | `idx-10` / v1, latest v2 | S003 | `insufficient_evidence`, `pending_source_update` |
| Recovered, 14:24:25.857281 | `idx-11` / v2 | Empty | `degraded`, v2 evidence retained, no abstention |

S003 changes from snapshot
`S003:61d56a81611318d0061addd396f24506e4c4ba1ec549ebbbc4fbef2f5ad5bd1b`
to
`S003:3e7a4e1dd60f3e33c992f3e304a0e149a9f506da03cdc87fe455678fc51226e9`.
The recovered Retrieval and Gateway responses agree on `idx-11` and S003 v2;
unchanged S005 and S010 retain v1 provenance. This supports the saved demonstration
of source-specific refusal followed by recovery to a newly published generation.
The JSON does not contain process stop/start commands or broker restart logs.

## Report wording

> In the saved 19 November demonstration, the affected S003 question abstained
> while Collector v2 was ahead of indexed v1, while the unaffected control
> continued returning evidence in all five trials. After recovery, the affected
> question returned v2 evidence from `idx-11` and no longer abstained. These runs
> used evidence-only fallback; they validate update handling and evidence
> availability rather than generated-answer quality.

## Separate follow-up

ADR-0003's 15-minute stuck-update alert is not established by these response
records, and no matching implementation was found in the current Retrieval
module. Its owner should clarify implementation status alongside ADR-0002's
metric-only RabbitMQ quarantine decision. Q004's separate chunking ranks and
the broader 880-request evaluation were not validated by this review.
