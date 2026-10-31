"""Check the running Collector-to-browser path over real service boundaries."""
import json
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, '/app')
import httpx
import pika
from source_collector.collector import Collector

results = []

def record(name, detail):
    results.append(dict(name=name, status='passed', detail=detail))
    print(json.dumps(results[-1]), flush=True)
    Path('/results/product-check.json').write_text(json.dumps(results, indent=2))

def eventually(check):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(.5)
    raise AssertionError('Timed out waiting for pipeline')

def retrieve(question, version=None):
    return httpx.post('http://retrieval:8002/v1/retrieve', json={
        'request_id': uuid.uuid4().hex, 'question': question, 'index_version': version,
    }, timeout=5)

def collect(text):
    collector = Collector('/state/collector.sqlite3')
    try:
        result = collector.collect('DOCKER_CONNECTED', 'https://www.irishimmigration.ie/test/',
                                    lambda _: '<main>' + text + '</main>')
        row = collector.db.execute('SELECT payload_json FROM outbox WHERE event_id = ?',
                                  (f"DOCKER_CONNECTED:{result['source_version']}",)).fetchone()
        return json.loads(row[0])
    finally:
        collector.close()

eventually(lambda: httpx.get('http://web/').status_code == 200)
assert 'StudentPath' in httpx.get('http://web/').text
assert httpx.get('http://web/app.js').status_code == 200
record('frontend', 'HTML and JavaScript served by nginx')
token = 'pipeline' + uuid.uuid4().hex
first_text = 'Synthetic connected pipeline check ' + token + ' first revision. No immigration guidance.'
event = collect(first_text)

def indexed(payload):
    response = retrieve(token)
    if response.status_code != 200:
        return False
    data = response.json()
    return data if any(p['source_id'] == payload['source_id'] and
                       p['source_version'] == payload['source_version'] and
                       p['snapshot_id'] == payload['snapshot_id'] for p in data['passages']) else False

first = eventually(lambda: indexed(event))
first_version = first['index_version']
record('continuous_collector_to_retrieval', {'event_id': event['event_id'], 'index_version': first_version,
       'path': 'Collector → relay → RabbitMQ → continuous Indexer → shared SQLite → read-only Retrieval'})
second_event = collect('Synthetic connected pipeline check ' + token + ' second revision. No immigration guidance.')
second = eventually(lambda: indexed(second_event))
assert second['index_version'] != first_version
old = retrieve(token, first_version)
assert old.status_code == 200
assert any(p['text'] == first_text for p in old.json()['passages'])
assert not any(p['text'] == first_text for p in second['passages'])
assert retrieve(token, 'idx-9223372036854775807').status_code == 404
record('published_updates_and_pinned_versions', {'old': first_version, 'current': second['index_version']})

connection = pika.BlockingConnection(pika.URLParameters(os.environ['RABBITMQ_URL']))
try:
    channel = connection.channel()
    channel.confirm_delivery()
    queue = 'studentpath.local.updates'
    channel.basic_publish('', queue, json.dumps(second_event).encode(), mandatory=True,
        properties=pika.BasicProperties(delivery_mode=2, message_id=second_event['event_id']))
    marker = ('invalid-check-' + uuid.uuid4().hex).encode()
    channel.basic_publish('', queue, marker, mandatory=True,
        properties=pika.BasicProperties(delivery_mode=2))
    def quarantined():
        method, properties, body = channel.basic_get(queue=queue + '.deadletter', auto_ack=False)
        if method is None:
            return False
        channel.basic_ack(method.delivery_tag)
        return body == marker
    eventually(quarantined)
    assert retrieve(token).json()['index_version'] == second['index_version']
    record('duplicate_and_invalid_delivery', 'Duplicate did not republish index; malformed marker quarantined')
finally:
    connection.close()

response = httpx.post('http://web/v1/questions', json={'question': token}, timeout=30)
assert response.status_code == 200, response.text
answer = response.json()
assert answer['index_version'] == second['index_version']
assert any(s['snapshot_id'] == second_event['snapshot_id'] and token in s['passage'] for s in answer['sources'])
assert answer['status'] == 'degraded' and answer['fallback_used'] is True
record('product_question_with_published_index', answer)
assert httpx.get('http://web/readyz').status_code == 200
assert httpx.post('http://web/v1/questions', json={'question': 'x'}).status_code == 400
missing = httpx.post('http://web/v1/questions', json={'question': uuid.uuid4().hex}, timeout=30)
assert missing.status_code == 200 and missing.json()['status'] == 'insufficient_evidence'
record('readiness_and_missing_evidence', 'Ready; invalid question rejected; unrelated question refuses without evidence')
