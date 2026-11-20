# Q004: table structure lost during chunking

Owner: Kezhen Zhang · 2026-11-20

## Report text

The current indexer chunks cleaned text into overlapping windows of up to
120 words, with 20 words of overlap and a 4,000-character limit. This preserves
repeatable passage identities but does not preserve table structure. Q004 asks
which documents are required for a Stamp 2-to-graduate Stamp 1G renewal and
whether travel insurance is sufficient. Its source, S004, distinguishes first
registration from renewal in separate table columns. A window that loses the
graduate heading and combines both columns weakens retrieval and risks mixing
requirements from different procedures.

In the Retrieval owner's reproduction using Sunmin's saved snapshots, the
relevant answer row (reported at S004 line 68) ranked 67th with the current
ranker and 44th with a BM25 comparison. A prototype that chunks by table row
and prefixes each row with its heading and column label ranked it 2nd using
the current ranker. These are teammate-reported, single-case diagnostic
results; they have not been independently rerun here and do not establish
overall answer accuracy. They suggest that preserving context at extraction
and chunking is a useful next step before changing the ranking method.

The proposed fix is to retain heading, row and column boundaries in the
Collector-to-Indexer representation and produce bounded passages with the
relevant heading and column label attached. This requires agreement with the
Collector owner because flattening the HTML may already have removed those
boundaries. Generated passages must retain source provenance, use a new
`chunker_version`, and publish through the existing immutable-generation
mechanism. Evaluate the change against Q004 and its paraphrase, then rerun the
broader evaluation set for regressions. Keep first-registration and renewal
requirements separate, verify citation correctness, and compare retrieval
rank, recall at five and grounded answer quality on the same saved snapshots.

## Evidence and scope

- [Q004 gate entry](../../data/qa_gate_10_v1.json) already identifies the
  multi-column extraction risk; its stored end-to-end status remains `not_run`.
- [Current chunker](../../indexing_worker/chunking.py) supplies the window
  parameters above; no structure-aware chunker is shipped by this note.
- Rank figures come from the Retrieval owner's WhatsApp handoff supplied by
  Kezhen. Attach the original ranked outputs, snapshot identity and prototype
  revision before presenting those figures as independently reproduced results.
- This is a report contribution and proposed fix; the diagnostic ranks do not
  constitute a completed end-to-end evaluation of the project.
