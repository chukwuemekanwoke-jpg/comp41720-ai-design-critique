"""Three observable phases of the isolated, real-service pending-update demo."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import platform
import os
from pathlib import Path
import time
import uuid

import httpx

from source_collector.collector import Collector

FORM = 'PENDING_FORM'
FEE = 'PENDING_FEE'
RESULT = Path('/results/pending-update.json')


def collect(source_id, text):
    collector = Collector('/state/collector.sqlite3')
    try:
        # Canonical identity satisfies the existing allowlist. The injected
        # fetcher reads only synthetic HTML; no official website is contacted.
        result = collector.collect(source_id,
            f'https://www.irishimmigration.ie/synthetic-demo/{source_id.lower()}/',
            lambda _: f'<main><p>{text}</p></main>')
        assert result['status'] != 'fetch_failed', result
        return result
    finally:
        collector.close()


def eventually(check):
    end = time.monotonic() + 90
    while time.monotonic() < end:
        try:
            value = check()
            if value:
                return value
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError('Demo condition not reached within 90 seconds')


def status(source_id):
    response = httpx.get(f'http://collector:8001/sources/{source_id}/status', timeout=5)
    response.raise_for_status()
    return response.json()


def ask(question):
    request_id = 'demo-' + uuid.uuid4().hex
    response = httpx.post('http://gateway:8000/v1/questions',
        json={'question': question}, headers={'X-Request-ID': request_id}, timeout=30)
    if response.status_code != 200:
        return None
    body = response.json()
    assert body['request_id'] == response.headers['X-Request-ID'] == request_id
    return body


def evidence_matches(body, source_id, version, word):
    return bool(body and body['status'] == 'degraded' and body['fallback_used']
                and not body.get('abstention') and any(
                    s['source_id'] == source_id and s['source_version'] == version
                    and word in s['passage'] for s in body['sources']))


def save(report, phase, responses):
    report['phases'].append({'phase': phase,
        'at': datetime.now(timezone.utc).isoformat(), 'responses': responses})
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'phase': phase, 'result': 'passed', 'responses': responses}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['seed', 'before', 'pending', 'after'])
    phase = parser.parse_args().phase
    if phase == 'seed':
        print(collect(FORM, 'formprobe blue'))
        print(collect(FEE, 'feeprobe ten'))
        return
    if phase == 'before':
        versions = {sid: eventually(lambda sid=sid: status(sid)) for sid in (FORM, FEE)}
        form = eventually(lambda: (b if evidence_matches(b := ask('formprobe'), FORM, versions[FORM]['source_version'], 'blue') else None))
        fee = eventually(lambda: (b if evidence_matches(b := ask('feeprobe'), FEE, versions[FEE]['source_version'], 'ten') else None))
        report = {'revision': os.getenv('DEMO_REVISION', 'unknown'), 'complete': False,
            'python': platform.python_version(),
            'demo_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'Isolated real Docker services; synthetic evidence; no Ollama generation.',
            'initial_sources': versions, 'phases': []}
        save(report, phase, {'affected_question': form, 'unaffected_question': fee})
        return
    report = json.loads(RESULT.read_text())
    if phase == 'pending':
        collect(FORM, 'formprobe green')
        latest = status(FORM)
        assert latest['source_version'] > report['initial_sources'][FORM]['source_version']
        report['changed_source'] = latest
        def has_handover():
            b = ask('formprobe')
            if not b or b['status'] != 'insufficient_evidence' or not b.get('abstention'):
                return None
            affected = b['abstention']['affected_sources']
            assert len(affected) == 1 and affected[0]['source_id'] == FORM
            assert affected[0]['indexed_source_version'] == report['initial_sources'][FORM]['source_version']
            assert affected[0]['latest_source_version'] == latest['source_version']
            assert affected[0]['detected_at'] == latest['detected_at']
            assert b['answer'] is None and b['sources'] == [] and not b['fallback_used']
            assert b['model'] == {'name': 'policy-response', 'prompt_version': 'none'}
            assert b['index_version'] == report['phases'][0]['responses']['affected_question']['index_version']
            return b
        form = eventually(has_handover)
        fee = ask('feeprobe')
        assert evidence_matches(fee, FEE, report['initial_sources'][FEE]['source_version'], 'ten')
        save(report, phase, {'affected_question': form, 'unaffected_question': fee})
    else:
        form = eventually(lambda: (b if evidence_matches(b := ask('formprobe'), FORM,
            report['changed_source']['source_version'], 'green') else None))
        assert form['index_version'] != report['phases'][0]['responses']['affected_question']['index_version']
        fee = ask('feeprobe')
        assert evidence_matches(fee, FEE, report['initial_sources'][FEE]['source_version'], 'ten')
        report['complete'] = True
        save(report, phase, {'affected_question': form, 'unaffected_question': fee})


if __name__ == '__main__':
    main()
