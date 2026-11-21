# Collector source validation — 2026-11-16

Inputs: [candidate source manifest](../data/sources_manifest_v1.json) and
[candidate QA mapping](../data/qa_gate_10_v1.json). Each source ID below maps
to the canonical official ISD page in the manifest.

One live collection pass using the existing official HTTPS fetcher and
`main-text-v1` on 2026-11-16, 14:13 UTC. All ten fetches succeeded, yielded
non-empty cleaned text and created a version-1 snapshot in a fresh local SQLite
store. Version 1 describes this validation store, not a production version.
Evidence below was checked against the extracted text, not search snippets.

| Source / question | Cleaned characters | Evidence location and assessment |
| --- | ---: | --- |
| S001 / Q001 | 3,972 | **Supported.** Lines 10–11: written award notification, application window and current Stamp 2/registration card conditions. |
| S002 / Q002 | 17,378 | **Supported.** Line 74: graduate-specific employment conditions. Keep separate from dependent Stamp 1G. |
| S003 / Q003 | 10,377 | **Supported.** Lines 29–32: renewal window, course start and presence in Ireland. |
| S004 / Q004 | 67,627 | **Answer text present; context incomplete.** Lines 67–68 retain first-time/renewal column labels and pipe-separated cells, including the renewal insurance exclusion. The graduate-specific heading is missing from this row's context, so this is not a structurally complete extraction. See the Q004 limitation below. |
| S005 / Q005 | 31,698 | **Supported.** Lines 116–118: online change in qualifying cases; graduate transition is an explicit example. |
| S006 / Q006 | 17,117 | **Supported.** Line 16: attendance threshold and end-of-course examination for English-language students. |
| S007 / Q007 | 17,409 | **Supported as the general rule.** Lines 13 and 88 cover the end of graduate permission. Preserve the surrounding exceptional-circumstances caveat; do not infer individual outcomes. |
| S008 / Q008 | 3,753 | **Supported.** Lines 6–16: who must register, timeframe and the first-registration office and appointment. Do not infer the consequences of unavailable appointments from this answer. |
| S009 / Q009 | 7,587 | **Original answer partially supported; corrected answer supported.** Lines 6–11 support the direct-access funds amount for the stated non-visa cohort and duration. The course-fee language on line 17 belongs to the separate visa-required heading and was removed after evaluation-owner confirmation. |
| S010 / Q010 | 8,498 | **Supported.** Lines 7–8: existing permission must be valid and filing does not extend it. Do not use the dependent category table as evidence of the graduate pathway. |

Line numbers refer to the locally extracted UTF-8 text from this run and may
shift after a refresh. The local working directory
`.test-tmp-isd-validation/` has `attempts.jsonl` (canonical URL, timestamps,
version, snapshot ID and SHA-256), the cleaned text files, and
`official.sqlite3`. These generated artifacts are not committed.

**Initial result:** 10/10 fetched and extracted; the original Q009 answer needed
review. Its corrected funds-only answer is supported, but Q004's missing
category heading and retrieval failure remain unresolved.
No retrieval ranking, chunk-context preservation, generation, or end-to-end
selection gate was tested in the collection pass. Re-run after the v2 cleaner
lands to verify the evidence still survives extraction.

## Follow-up: Q004 retrieval and Q009 expected answer

For Q004, indexed all ten saved snapshots using the Collector snapshot API and
the actual Indexing Worker against a fresh SQLite database. Queried the real
`POST /v1/retrieve` handler with the exact Q004 question and `top_k=5`, using the
SQLite adapter and in-process HTTP clients. Baseline main: `04e5a41`; published
index: `idx-10` (309 passages). No live fetch, broker, Gateway, or model ran.

**Q004 did not pass retrieval.** The five returned source IDs, in order, were
S004, S005, S004, S007, S007. Neither S004 hit supplies the graduate renewal
column in context: the first is about a dependent registration and the third
is a different permission category despite containing renewal insurance text.
The S004 passage containing the first-time/renewal column labels, course-completion evidence and
renewal travel-insurance exclusion ranked **67th** (score 0.231), outside both
the requested five results and the endpoint's 20-result limit. This diagnostic
rank used the same ranker on the full index. The relevant passage ID is
`P:917b66e0ff913ab7bcf884bdd3974427b8ff82e9c9a5ff0da7764082c3d9d384`.
The exact retrieval output is saved locally as
`.test-tmp-isd-validation/q004-retrieval.json`. Ask the Retrieval owner to
review ranking and the Indexer owner to check that table headings and column
context stay with the relevant passage. No services were changed.

For Q009, the proposed expected answer now states only the direct-access
amount supported by the non-visa-required section of S009. The old
course-fee clause came from a different cohort. Emeka confirmed removal in the
team discussion on 19 November. The gate records that reason; this correction
does not establish generated-answer correctness.

The later [Q004 limitation](evaluation/q004-chunking-limitation.md) records the
missing graduate heading and mixed column context, plus Emeka's BM25 and
structure-aware prototype comparisons. Those two prototype ranks were reported
by Emeka, not independently rerun by this Collector validation. Cleaning and
chunking improvements remain future work; existing snapshots were not rewritten.

See [Collector evaluation evidence](evaluation/collector-validation-summary.md)
for the frozen 880-request run and the separately verified recovery record.
