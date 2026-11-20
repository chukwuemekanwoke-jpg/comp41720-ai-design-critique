import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from answer_service.app import create_app
from answer_service.config import Settings
from answer_service.eligibility_policy import requests_personal_decision, contains_personal_decision

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('question', [
    "I finished my master's in August and my results came out last week. Am I eligible for Stamp 1G?",
    'Decide for me: do I qualify for the graduate programme with a level 8 degree from DCU?',
    'Will my Stamp 2 renewal be refused?',
    'Would I be eligible for this permission?',
    'Could you say whether I qualify for this programme?',
])
@pytest.mark.parametrize('mode', ['ollama', 'evidence_only'])
def test_personal_requests_bypass_model_and_fallback(question, mode):
    payload=json.loads((ROOT/'data/answer_request_demo.json').read_text());payload['question']=question
    def model(request): pytest.fail('Personal decision must bypass model')
    with TestClient(create_app(Settings(generation_mode=mode),transport=httpx.MockTransport(model))) as client:
        response=client.post('/v1/answers',json=payload,headers={'X-Request-ID':'eligibility-check'})
    body=response.json()
    assert response.status_code==200
    assert body['status']=='insufficient_evidence'
    assert body['answer'] is None and body['sources']==[] and body['checklist']==[]
    assert body['fallback_used'] is False and 'refusal_reason' not in body
    assert body['model']=={'name':'policy-response','prompt_version':'eligibility-policy-v1'}
    assert body['index_version']==payload['index_version']
    assert body['last_success_at']==payload['last_success_at']
    assert body['request_id']==response.headers['X-Request-ID']=='eligibility-check'

@pytest.mark.parametrize('claim', [
    'No, you are not eligible for Stamp 1G until final results are issued.',
    'Yes, you qualify for the graduate programme, provided the conditions hold.',
    'Your Stamp 1G application has been approved.',
])
@pytest.mark.parametrize('location', ['answer','checklist'])
def test_generated_decisions_are_suppressed(claim,location):
    payload=json.loads((ROOT/'data/answer_request_demo.json').read_text())
    def model(request):
        output={'status':'answered','answer':claim if location=='answer' else 'A blue form.',
                'checklist':[claim] if location=='checklist' else [],'source_indices':[1]}
        return httpx.Response(200,json={'model':'test-model','done':True,'done_reason':'stop',
            'message':{'role':'assistant','content':json.dumps(output)}})
    with TestClient(create_app(Settings(generation_mode='ollama'),transport=httpx.MockTransport(model))) as client:
        body=client.post('/v1/answers',json=payload).json()
    assert body['status']=='insufficient_evidence' and body['answer'] is None
    assert body['sources']==[] and body['checklist']==[] and not body['fallback_used']

@pytest.mark.parametrize('question', [
    'What are the eligibility requirements for Stamp 1G?',
    'What documents must I bring to registration?',
    'How do I apply for graduate permission?',
    'Tell me whether I am required to bring a passport.',
    'Can I work while holding Stamp 1G?',
    'What happens if I forget to renew?',
])
def test_general_guidance_is_not_personal_decision_request(question):
    assert not requests_personal_decision(question)

@pytest.mark.parametrize('answer', [
    'I cannot determine whether you qualify.',
    'I cannot determine if you are eligible.',
    'If you are eligible, the application instructions describe the next steps.',
    'Applicants must meet the published conditions.',
])
def test_uncertainty_and_general_conditions_are_not_claims(answer):
    assert not contains_personal_decision(answer)


def test_pending_update_takes_precedence_over_eligibility():
    payload=json.loads((ROOT/'data/answer_abstention_demo.json').read_text())
    payload['question']='Am I eligible for Stamp 1G?'
    with TestClient(create_app(Settings())) as client:body=client.post('/v1/answers',json=payload).json()
    assert body['abstention']['reason']=='pending_source_update'
