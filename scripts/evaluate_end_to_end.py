"""End-to-end evaluation through a running Gateway; preserves every response and failure.

For each case in data/evaluation/end_to_end_v1.json it asks Retrieval once (top five
sources and scores, which are deterministic) and the Gateway once per trial (the
answer, which may not be). Results are saved after every request, so an interrupted
run still leaves a partial report marked `completed: false`.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/evaluation/end_to_end_v1.json"
GROUNDED = {"answered", "degraded"}


def case_checks(case, body, http_status, retrieved_sources):
    """Automatic checks. Forbidden-term matches are review flags, not failures."""
    if http_status != 200:
        return ["http_status"], []
    failures, flags = [], []
    if body.get("status") not in case["acceptable_statuses"]:
        failures.append("status")
    if body.get("status") == "answered" and not body.get("sources"):
        failures.append("uncited_answer")
    text = json.dumps([body.get("answer"), body.get("checklist")], ensure_ascii=False).lower()
    if body.get("status") == "answered" and any(t.lower() not in text for t in case["required_terms"]):
        failures.append("required_terms")
    flags += [f"forbidden:{t}" for t in case["forbidden_terms"] if t.lower() in text]
    if expects_retrieval(case) and not set(case["expected_sources"]) & set(retrieved_sources):
        failures.append("retrieval_miss")
    if case["category"] == "pending_update" and "insufficient_evidence" in case["acceptable_statuses"]:
        if (body.get("abstention") or {}).get("reason") != "pending_source_update":
            failures.append("pending_abstention")
    return failures, flags


def expects_retrieval(case):
    return bool(case["expected_sources"]) and set(case["acceptable_statuses"]) <= GROUNDED


def best_threshold(grounded_scores, refusal_scores):
    """Pick the score cut that best separates answerable from out-of-collection cases.

    Answerable cases should score at or above the cut, refusals below it. Returns the
    candidate with the most correct classifications and its error counts. Ties go to
    the higher cut: refusing an answerable question is the safer error here than
    answering one the collection cannot support.

    Cuts sit midway between adjacent observed scores, plus one below the lowest
    (answer everything) and one above the highest (refuse everything), so every
    distinct split of the scores is tried and no cut lands on a score itself.
    """
    if not grounded_scores or not refusal_scores:
        return None
    scores = sorted(set(grounded_scores) | set(refusal_scores))
    candidates = ([0.0] + [(low + high) / 2 for low, high in zip(scores, scores[1:])]
                  + [scores[-1] + 0.01])
    best = None
    for cut in candidates:
        correct = sum(s >= cut for s in grounded_scores) + sum(s < cut for s in refusal_scores)
        if best is None or correct >= best["correct"]:
            best = {"threshold": round(cut, 4), "correct": correct,
                    "total": len(grounded_scores) + len(refusal_scores),
                    "answerable_below": sum(s < cut for s in grounded_scores),
                    "refusals_at_or_above": sum(s >= cut for s in refusal_scores)}
    return best


def summarise(dataset, results, retrievals):
    cases = {c["id"]: c for c in dataset["cases"]}
    by_case = defaultdict(list)
    for row in results:
        by_case[row["case_id"]].append(row)
    per_category = defaultdict(lambda: {"requests": 0, "passed": 0})
    for row in results:
        bucket = per_category[cases[row["case_id"]]["category"]]
        bucket["requests"] += 1
        bucket["passed"] += not row["failures"]
    graded = [c for c in cases.values() if expects_retrieval(c) and c["id"] in retrievals]
    recall_hits = [c["id"] for c in graded if set(c["expected_sources"]) & set(retrievals[c["id"]]["sources"])]
    changing = {cid: dict(Counter(r["status"] for r in rows)) for cid, rows in by_case.items()
                if len({r["status"] for r in rows}) > 1}
    top = {cid: r["top_score"] for cid, r in retrievals.items()}
    grounded_scores = [top[c["id"]] for c in graded]
    refusal_scores = [top[cid] for cid, c in cases.items()
                      if c["category"] == "out_of_collection" and cid in top]
    return {
        "requests": len(results),
        "automatic_passes": sum(not r["failures"] for r in results),
        "failures_by_check": dict(Counter(f for r in results for f in r["failures"])),
        "review_flags": {cid: sorted({f for r in rows for f in r["flags"]})
                         for cid, rows in by_case.items() if any(r["flags"] for r in rows)},
        "by_category": dict(per_category),
        "retrieval_recall_at_5": {"cases": len(graded), "hits": len(recall_hits),
                                  "misses": sorted(c["id"] for c in graded if c["id"] not in recall_hits)},
        "nondeterminism": {"cases_with_repeats": sum(len(rows) > 1 for rows in by_case.values()),
                           "cases_whose_status_changed": changing},
        "threshold_suggestion": best_threshold(grounded_scores, refusal_scores),
    }


def post(client, path, body, request_id):
    response = client.post(path, json=body, headers={"X-Request-ID": request_id})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"raw": response.text[:2000]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8000")
    parser.add_argument("--retrieval-url", default="http://127.0.0.1:8002")
    parser.add_argument("--cases", type=Path, default=DATASET)
    parser.add_argument("--categories", help="Comma-separated subset, e.g. answerable,out_of_collection")
    parser.add_argument("--include-pending", action="store_true",
                        help="Run pending_update cases; only after their Collector setup is in place")
    parser.add_argument("--trials", type=int, default=1, help="Gateway requests per case (20 for non-determinism)")
    parser.add_argument("--timeout", type=float, default=35.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.trials <= 50:
        parser.error("--trials must be between 1 and 50")
    if args.output.exists():
        parser.error("output already exists; choose a new path so earlier results are preserved")

    raw = args.cases.read_bytes()
    dataset = json.loads(raw)
    wanted = set(args.categories.split(",")) if args.categories else None
    selected = [c for c in dataset["cases"]
                if (wanted is None or c["category"] in wanted)
                and (c["category"] != "pending_update" or args.include_pending)]

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()

    report = {"started_at": datetime.now(timezone.utc).isoformat(), "dataset": dataset["name"],
              "dataset_status": dataset.get("status"), "dataset_sha256": hashlib.sha256(raw).hexdigest(),
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "git_commit": git("rev-parse", "HEAD"), "working_tree": git("status", "--short"),
              "gateway_url": args.gateway_url, "retrieval_url": args.retrieval_url,
              "trials_per_case": args.trials, "case_ids": [c["id"] for c in selected],
              "retrievals": {}, "results": [], "completed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(args.output)

    save()
    try:
        with httpx.Client(base_url=args.retrieval_url, timeout=args.timeout, trust_env=False) as retrieval, \
                httpx.Client(base_url=args.gateway_url, timeout=args.timeout, trust_env=False) as gateway:
            for case in selected:
                request_id = f"e2e-{case['id']}-{uuid.uuid4().hex[:8]}"
                status, body = post(retrieval, "/v1/retrieve",
                                    {"request_id": request_id, "question": case["question"], "top_k": 5}, request_id)
                passages = body.get("passages", []) if status == 200 else []
                report["retrievals"][case["id"]] = {
                    "http_status": status, "index_version": body.get("index_version"),
                    "sources": [p["source_id"] for p in passages],
                    "scores": [p["score"] for p in passages],
                    "top_score": passages[0]["score"] if passages else 0.0,
                    "pending_sources": [p["source_id"] for p in body.get("pending_sources", [])],
                    "freshness_confirmed": body.get("freshness_confirmed")}
                for trial in range(1, args.trials + 1):
                    request_id = f"e2e-{case['id']}-{trial}-{uuid.uuid4().hex[:8]}"
                    started = time.perf_counter()
                    status, body = post(gateway, "/v1/questions", {"question": case["question"]}, request_id)
                    failures, flags = case_checks(case, body, status, report["retrievals"][case["id"]]["sources"])
                    report["results"].append({
                        "case_id": case["id"], "trial": trial, "http_status": status,
                        "status": body.get("status"), "seconds": round(time.perf_counter() - started, 3),
                        "failures": failures, "flags": flags, "response": body})
                    save()
                rows = [r for r in report["results"] if r["case_id"] == case["id"]]
                print(f"{case['id']} {case['category']}: {sum(not r['failures'] for r in rows)}/{len(rows)} passed",
                      flush=True)
        report["completed"] = len(report["results"]) == len(selected) * args.trials
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["summary"] = summarise(dataset, report["results"], report["retrievals"])
        save()
    print(json.dumps(report["summary"], indent=2), flush=True)
    return 0 if report["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
