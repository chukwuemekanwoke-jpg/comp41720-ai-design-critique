"""Scoring logic of scripts/evaluate_end_to_end.py; no network or running services."""
import pytest

from scripts.evaluate_end_to_end import best_threshold, case_checks, summarise

GROUNDED_CASE = {"id": "A01", "category": "answerable", "acceptable_statuses": ["answered", "degraded"],
                 "expected_sources": ["S001"], "required_terms": ["six months"], "forbidden_terms": []}
REFUSAL_CASE = {"id": "O01", "category": "out_of_collection", "acceptable_statuses": ["insufficient_evidence"],
                "expected_sources": [], "required_terms": [], "forbidden_terms": []}
ELIGIBILITY_CASE = {"id": "E01", "category": "eligibility_request",
                    "acceptable_statuses": ["answered", "insufficient_evidence", "degraded"],
                    "expected_sources": [], "required_terms": [], "forbidden_terms": ["you are eligible"]}
SOURCE = {"source_id": "S001"}


def answered(text):
    return {"status": "answered", "answer": text, "checklist": [], "sources": [SOURCE]}


def test_correct_grounded_answer_passes():
    assert case_checks(GROUNDED_CASE, answered("Apply within six months."), 200, ["S001"]) == ([], [])


def test_retrieval_miss_and_missing_terms_fail():
    failures, _ = case_checks(GROUNDED_CASE, answered("Apply soon."), 200, ["S009"])
    assert failures == ["required_terms", "retrieval_miss"]


def test_uncited_answer_and_wrong_status_fail():
    failures, _ = case_checks(REFUSAL_CASE, {"status": "answered", "answer": "x", "sources": []}, 200, [])
    assert failures == ["status", "uncited_answer"]


def test_forbidden_terms_flag_for_review_instead_of_failing():
    body = answered("I cannot determine whether you are eligible.")
    failures, flags = case_checks(ELIGIBILITY_CASE, body, 200, [])
    assert failures == [] and flags == ["forbidden:you are eligible"]


def test_http_error_is_a_single_failure():
    assert case_checks(GROUNDED_CASE, {}, 504, []) == (["http_status"], [])


def test_pending_update_case_requires_the_abstention_reason():
    case = {"id": "U01", "category": "pending_update", "acceptable_statuses": ["insufficient_evidence"],
            "expected_sources": ["S003"], "required_terms": [], "forbidden_terms": []}
    plain = {"status": "insufficient_evidence", "answer": None, "checklist": [], "sources": []}
    assert case_checks(case, plain, 200, ["S003"])[0] == ["pending_abstention"]
    abstained = plain | {"abstention": {"reason": "pending_source_update"}}
    assert case_checks(case, abstained, 200, ["S003"])[0] == []


def test_threshold_separates_scores_and_reports_errors():
    best = best_threshold([0.8, 0.6, 0.3], [0.2, 0.1, 0.5])
    assert best["threshold"] == pytest.approx(0.55)
    assert best["correct"] == 5 and best["answerable_below"] == 1 and best["refusals_at_or_above"] == 0
    assert best_threshold([], [0.1]) is None


def test_threshold_can_refuse_everything():
    # Refusals outscore every answerable case: the best cut is above all scores.
    best = best_threshold([0.2], [0.9, 0.8])
    assert best["threshold"] > 0.9
    assert best["correct"] == 2 and best["answerable_below"] == 1 and best["refusals_at_or_above"] == 0
    # Kezhen's case from the #32 review: tied top refusals.
    best = best_threshold([0.1], [0.9, 0.9])
    assert best["threshold"] > 0.9 and best["correct"] == 2


def test_threshold_separates_a_refusal_tied_with_the_lowest_answerable_score():
    best = best_threshold([0.5, 0.7], [0.3, 0.5])
    assert best["correct"] == 3 and 0.5 < best["threshold"] <= 0.7


@pytest.mark.parametrize("grounded, refusals", [
    ([0.50002], [0.50001]),  # Kezhen's #32 review: rounding to 0.5 lost a correct case
    ([0.8, 0.6, 0.3], [0.2, 0.1, 0.5]),
    ([0.1], [0.9, 0.9]),
    ([0.5, 0.7], [0.3, 0.5]),
    ([0.123456789, 0.123456788], [0.123456787]),
])
def test_returned_threshold_reproduces_reported_counts(grounded, refusals):
    best = best_threshold(grounded, refusals)
    cut = best["threshold"]
    assert sum(s >= cut for s in grounded) + sum(s < cut for s in refusals) == best["correct"]
    assert sum(s < cut for s in grounded) == best["answerable_below"]
    assert sum(s >= cut for s in refusals) == best["refusals_at_or_above"]


def test_summary_counts_recall_and_changing_outcomes():
    dataset = {"cases": [GROUNDED_CASE, REFUSAL_CASE]}
    retrievals = {"A01": {"sources": ["S002"], "top_score": 0.4},
                  "O01": {"sources": [], "top_score": 0.0}}
    results = [{"case_id": "A01", "status": "answered", "failures": ["retrieval_miss"], "flags": []},
               {"case_id": "A01", "status": "degraded", "failures": ["retrieval_miss"], "flags": []},
               {"case_id": "O01", "status": "insufficient_evidence", "failures": [], "flags": []}]
    summary = summarise(dataset, results, retrievals)
    assert summary["retrieval_recall_at_5"] == {"cases": 1, "hits": 0, "misses": ["A01"]}
    assert summary["nondeterminism"]["cases_whose_status_changed"] == {"A01": {"answered": 1, "degraded": 1}}
    assert summary["by_category"]["out_of_collection"] == {"requests": 1, "passed": 1}
    assert summary["threshold_suggestion"]["threshold"] == pytest.approx(0.2)
