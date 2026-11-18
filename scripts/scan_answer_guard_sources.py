from pathlib import Path
import argparse, hashlib, importlib.util, json, subprocess
parser=argparse.ArgumentParser(description='Scan frozen manifest-verified source texts with the current instruction guard.')
parser.add_argument('corpus',type=Path)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
corpus=args.corpus
if args.output.exists():
 raise SystemExit('Output exists; choose a new report path')
guard_path=root/'answer_service/instruction_guard.py'
spec=importlib.util.spec_from_file_location('guard',guard_path); guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
manifest=json.loads((corpus/'manifest.json').read_text()); rows=[]
assert len(manifest)==10
for entry in manifest:
 p=corpus/'cleaned'/f"{entry['source_id']}.txt"; raw=p.read_bytes(); text=raw.decode('utf-8'); digest=hashlib.sha256(raw).hexdigest()
 assert digest==entry['content_sha256'],p
 lines=text.splitlines(); matches=[{'line':i,'text':line} for i,line in enumerate(lines,1) if guard.contains_instruction_override(line)]
 rows.append({**entry,'bytes':len(raw),'lines':len(lines),'hash_verified':True,'whole_snapshot_flagged':guard.contains_instruction_override(text),'flagged_lines':matches})
assert len(list((corpus/'cleaned').glob('*.txt')))==10
report={'scan_date':'2026-11-18','guard_version':guard.GUARD_VERSION,'guard_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'guard_sha256':hashlib.sha256(guard_path.read_bytes()).hexdigest(),'manifest_sha256':hashlib.sha256((corpus/'manifest.json').read_bytes()).hexdigest(),'method':'Run unchanged guard against each complete UTF-8 snapshot and each non-empty/empty line independently. Full-document check also covers adjacent override phrases split across lines. No model calls, retrieval or Indexer chunking performed.','total_sources':len(rows),'total_lines':sum(x['lines'] for x in rows),'total_bytes':sum(x['bytes'] for x in rows),'flagged_snapshots':sum(x['whole_snapshot_flagged'] for x in rows),'flagged_lines':sum(len(x['flagged_lines']) for x in rows),'missing_sources':[],'sources':rows,'limitations':['Frozen 16 November corpus, not current website policy.','No observed matches on this corpus does not establish zero false positives generally.','Indexer-generated passage boundaries and question text were not evaluated.','No answer accuracy or attack-detection performance claim.']}
out=args.output;out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['guard_version','total_sources','total_lines','total_bytes','flagged_snapshots','flagged_lines']}))
