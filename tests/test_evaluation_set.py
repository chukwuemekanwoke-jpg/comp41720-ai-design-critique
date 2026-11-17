"""Structural checks for the end-to-end evaluation set; they do not score answers."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET = json.loads((ROOT / "data/evaluation/end_to_end_v1.json").read_text(encoding="utf-8"))
GATE = {q["question_id"]: q for q in json.loads(
    (ROOT / "data/qa_gate_10_v1.json").read_text(encoding="utf-8"))["questions"]}
SOURCES = {s["source_id"] for s in json.loads(
    (ROOT / "data/sources_manifest_v1.json").read_text(encoding="utf-8"))["sources"]}
STATUSES = {"answered", "insufficient_evidence", "degraded"}
CASES = SET["cases"]


def test_size_and_unique_ids():
    assert 40 <= len(CASES) <= 50
    assert len({c["id"] for c in CASES}) == len(CASES)


def test_covers_the_categories_the_feedback_asked_for():
    counts = Counter(c["category"] for c in CASES)
    assert counts["answerable"] == len(GATE)
    assert counts["out_of_collection"] >= 5      # questions the collection cannot answer
    assert counts["eligibility_request"] >= 5    # decisions the system must refuse
    assert counts["injection"] >= 3
    assert counts["pending_update"] >= 2         # ADR-0003 abstention and its unaffected control


def test_references_are_real():
    for case in CASES:
        assert set(case["expected_sources"]) <= SOURCES, case["id"]
        for qid in (case["based_on"] or "").split("+"):
            assert not qid or qid in GATE, case["id"]
        assert case["acceptable_statuses"] and set(case["acceptable_statuses"]) <= STATUSES, case["id"]


def test_answerable_cases_copy_the_gate_exactly():
    for case in (c for c in CASES if c["category"] == "answerable"):
        gate = GATE[case["based_on"]]
        assert case["question"] == gate["question"], case["id"]
        assert case["expected_answer"] == gate["expected_answer"], case["id"]
        assert case["expected_sources"] == [gate["source_id"]], case["id"]
        assert case["review_status"] == "verified_in_gate", case["id"]


def test_grounded_cases_name_their_evidence_and_refusals_do_not():
    for case in CASES:
        if set(case["acceptable_statuses"]) <= {"answered", "degraded"}:
            assert case["expected_sources"], case["id"]
            # An expected answer may be pending only while the case awaits evidence review.
            assert case["expected_answer"] or case["review_status"] == "needs_team_review", case["id"]
        if case["category"] == "out_of_collection":
            assert case["acceptable_statuses"] == ["insufficient_evidence"] and not case["expected_sources"]


def test_eligibility_requests_forbid_personal_decisions():
    for case in (c for c in CASES if c["category"] == "eligibility_request"):
        assert "you are eligible" in case["forbidden_terms"], case["id"]
