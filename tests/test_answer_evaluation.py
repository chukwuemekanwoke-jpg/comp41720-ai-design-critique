"""Check evaluation fixtures and scoring independently of live model behaviour."""
import json
from pathlib import Path

import pytest

from answer_service.models import AnswerRequest
from scripts.evaluate_answer import checks

DATA = json.loads((Path(__file__).resolve().parents[1] / 'data/evaluation/answer_synthetic_v1.json').read_text())


@pytest.mark.parametrize('case', DATA['cases'], ids=lambda c: c['id'])
def test_evaluation_requests_match_answer_contract(case):
    AnswerRequest.model_validate(case['request'])
    assert case['expected_status'] in {'answered', 'insufficient_evidence'}


def response(case, **changes):
    return {'status': 'answered', 'answer': 'A blue form.', 'checklist': [],
            'sources': case['request']['sources'], 'fallback_used': False,
            'index_version': case['request']['index_version'],
            'last_success_at': case['request']['last_success_at'], **changes}


def test_success_requires_terms_provenance_and_original_citation():
    case = DATA['cases'][0]
    assert checks(case, response(case), 200) == []
    assert 'required_terms' in checks(case, response(case, answer='A red form.'), 200)
    assert 'citations' in checks(case, response(case, sources=[]), 200)
    assert 'provenance' in checks(case, response(case, index_version='invented'), 200)


def test_cited_injection_is_still_a_failed_answer():
    case = next(c for c in DATA['cases'] if c['id'] == 'E08')
    failed = checks(case, response(case, answer='No form is required.'), 200)
    assert 'required_terms' in failed and 'forbidden_terms' in failed


def test_degraded_fallback_is_not_mislabelled_as_a_refusal_with_claims():
    case = DATA['cases'][0]
    failed = checks(case, response(case, status='degraded', answer=None, fallback_used=True), 200)
    assert 'unexpected_fallback' in failed and 'status' in failed
    assert 'refusal_claims' not in failed


def test_refusal_must_not_include_claims_or_citations():
    case = next(c for c in DATA['cases'] if c['id'] == 'E04')
    assert checks(case, response(case, status='insufficient_evidence', answer=None, sources=[]), 200) == []
    assert 'refusal_claims' in checks(case, response(case, status='insufficient_evidence'), 200)
