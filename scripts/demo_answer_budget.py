"""Opt-in actual Ollama check using a temporary one-attempt daily ledger."""
import argparse
from prometheus_client.parser import text_string_to_metric_families
from datetime import datetime,timezone
import hashlib,json,subprocess,tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import httpx
from answer_service.app import create_app
from answer_service.config import Settings

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
if args.output and args.output.exists():
 parser.error('Choose a new output path; existing evidence is never overwritten')
root=Path(__file__).resolve().parents[1]
payload=json.loads((root/'data/answer_request_demo.json').read_text())
with httpx.Client(base_url='http://127.0.0.1:11434',timeout=5,trust_env=False) as c:
 r=c.get('/api/version');r.raise_for_status();runtime=r.json()
 r=c.get('/api/tags');r.raise_for_status();tags=r.json()
with tempfile.TemporaryDirectory(prefix='studentpath-budget-check-') as d:
 config=Settings(generation_mode='ollama',daily_token_limit=8448,daily_budget_db=str(Path(d)/'budget.sqlite3'))
 with TestClient(create_app(config)) as c:
  first=c.post('/v1/answers',json=payload)
  second=c.post('/v1/answers',json=payload)
  m=c.get('/metrics').text
 assert first.status_code==200 and first.json()['status']=='answered',first.text
 assert second.status_code==200 and second.json()['status']=='degraded',second.text
 assert second.json()['sources']==payload['sources']
 assert 'studentpath_answer_budget_rejections_total{reason="exhausted"} 1.0' in m
 with TestClient(create_app(config)) as c:
  third=c.post('/v1/answers',json=payload)
  restarted_metrics=c.get('/metrics').text
 assert third.status_code==200 and third.json()['status']=='degraded'
 counts=[s.value for f in text_string_to_metric_families(restarted_metrics) for s in f.samples
         if s.name=='studentpath_answer_model_attempts_total']
 assert sum(counts)==0, 'Restarted app made a model call despite exhausted quota'
 report={'at':datetime.now(timezone.utc).isoformat(),'scope':'Actual host Ollama and Answer app via TestClient; no Gateway/Docker.',
  'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
  'dirty_tree':subprocess.check_output(['git','status','--short'],text=True),
  'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('answer_service').glob('*.py'))},
  'daily_allowance':8448,'charge_per_attempt':8448,'model':'llama3.2:3b','ollama':runtime,'installed_models':tags,
  'responses':[first.json(),second.json(),third.json()],
  'observations':['First request answered','Second request fell back without budget for another attempt','New app instance with same ledger still denied generation'],
  'limits':'Conservative context-plus-output admission charges, not exact measured daily usage. Temporary ledger deleted after test.'}
 if args.output:
  args.output.parent.mkdir(parents=True,exist_ok=True)
  args.output.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'statuses':[x['status'] for x in report['responses']],
                   'report':str(args.output) if args.output else None}))
