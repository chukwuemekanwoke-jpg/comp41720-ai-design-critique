# Saved official-source guard scan, 18 November 2026

Sunmin supplied ten frozen ISD snapshots collected on 16 November. All ten
cleaned UTF-8 files matched the SHA-256 values in the supplied manifest.
The unchanged instruction-guard-v2 at PR29 commit 8acc303 was applied to each
complete snapshot and each of its lines independently.

- Sources: 10/10 present and hash-verified.
- Input: 185,793 bytes, 1,006 lines.
- Complete snapshots flagged: 0/10.
- Lines flagged: 0/1,006.
- No missing files or hash mismatches.

No guard false positive was observed on these inputs. No runtime changes were
needed. This is a saved-source guard check, not a current-policy audit,
retrieval evaluation, answer-quality result or security guarantee. Indexer
passage boundaries and user questions were not evaluated.

Reproduce from the repository with the supplied extracted snapshot directory:

```sh
python scripts/scan_answer_guard_sources.py /path/to/StudentPath-ISD-snapshots-2026-11-16 --output /tmp/guard-source-scan.json
```

The scanner refuses to overwrite an existing report. Raw results in
answer-guard-real-sources-2026-11-18.json record source identities, hashes,
guard version/hash/commit and per-file observations. The Collector database
and original snapshots were left unchanged; neither is copied into the repo.
