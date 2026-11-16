"""Repeatable Answer-only local model evaluation; preserves failures and responses."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

import httpx
from fastapi.testclient import TestClient

from answer_service.app import create_app
from answer_service.config import Settings
from answer_service.instruction_guard import GUARD_VERSION
from answer_service.ollama import PROMPT_VERSION, SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]


def checks(case, body, http_status):
    """Limited automatic checks, not a semantic support or legal accuracy judge."""
    request = case['request']
    failures = []
    if http_status != 200:
        return ['http_status']
    if body.get('status') != case['expected_status']:
        failures.append('status')
    text = json.dumps([body.get('answer'), body.get('checklist')], ensure_ascii=False).lower()
    if any(term.lower() not in text for term in case['required_terms']):
        failures.append('required_terms')
    if any(term.lower() in text for term in case['forbidden_terms']):
        failures.append('forbidden_terms')
    if body.get('index_version') != request['index_version'] or body.get('last_success_at') != request.get('last_success_at'):
        failures.append('provenance')
    if body.get('fallback_used') is not False:
        failures.append('unexpected_fallback')
    if body.get('status') == 'answered':
        supplied = request['sources']
        if not body.get('sources') or any(source not in supplied for source in body['sources']):
            failures.append('citations')
    elif body.get('status') == 'insufficient_evidence' and (body.get('answer') is not None or body.get('checklist') or body.get('sources')):
        failures.append('refusal_claims')
    if request.get('abstention') and body.get('abstention', {}).get('reason') != 'pending_source_update':
        failures.append('pending_handover')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=ROOT / 'data/evaluation/answer_synthetic_v1.json')
    parser.add_argument('--trials', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='llama3.2:3b')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    if not 1 <= args.trials <= 100:
        parser.error('--trials must be between 1 and 100')
    if args.output.exists():
        parser.error('output already exists; choose a new path to preserve previous results')
    fixture_bytes = args.cases.read_bytes()
    dataset = json.loads(fixture_bytes)
    settings = Settings(generation_mode='ollama', model=args.model, ollama_url=args.ollama_url)
    # Metadata calls fail before the run if the local runtime is unavailable.
    with httpx.Client(base_url=args.ollama_url, timeout=5, trust_env=False) as model:
        version = model.get('/api/version'); version.raise_for_status()
        tags = model.get('/api/tags'); tags.raise_for_status()
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=ROOT, text=True).strip()
    report = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'scope': dataset['scope'], 'dataset': dataset['name'],
        'dataset_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'git_commit': git('rev-parse', 'HEAD'), 'working_tree': git('status', '--short'),
        'python': platform.python_version(), 'platform': platform.platform(),
        'settings': asdict(settings), 'prompt_version': PROMPT_VERSION, 'guard_version': GUARD_VERSION,
        'prompt_sha256': hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        'ollama_version': version.json(), 'installed_models': tags.json(),
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((ROOT / 'answer_service').glob('*.py'))},
        'trials_per_case': args.trials, 'results': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = args.output.with_suffix(args.output.suffix + '.tmp')
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        temporary.replace(args.output)
    save()
    try:
        with TestClient(create_app(settings)) as client:
            for case in dataset['cases']:
                for trial in range(1, args.trials + 1):
                    request_id = f"eval-{case['id']}-{trial}"
                    started = time.perf_counter()
                    response = client.post('/v1/answers', json=case['request'], headers={'X-Request-ID': request_id})
                    body = response.json()
                    failures = checks(case, body, response.status_code)
                    if body.get('request_id') != request_id or response.headers.get('X-Request-ID') != request_id:
                        failures.append('request_id')
                    report['results'].append({'case_id': case['id'], 'category': case['category'],
                        'trial': trial, 'seconds': time.perf_counter() - started,
                        'http_status': response.status_code, 'failures': failures, 'response': body})
                    save()
                rows = [r for r in report['results'] if r['case_id'] == case['id']]
                print(f"{case['id']} {case['category']}: {sum(not r['failures'] for r in rows)}/{len(rows)} automatic checks passed", flush=True)
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['completed'] = len(report['results']) == len(dataset['cases']) * args.trials
        report['summary'] = {'requests': len(report['results']),
            'automatic_passes': sum(not r['failures'] for r in report['results']),
            'failures_by_check': dict(Counter(f for r in report['results'] for f in r['failures']))}
        save()
    print(json.dumps(report['summary']), flush=True)
    # A report containing failed expectations is still written in full.
    return 0 if report['completed'] and not report['summary']['failures_by_check'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
