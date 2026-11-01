#!/usr/bin/env python3
"""Frozen 3-cell native DuckDB filter attribution run."""
import csv, hashlib, io, json, os, platform, random, re, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
I=ROOT/'source/integration'; DATA=ROOT/'source/data'; OUT=ROOT/'source/results/duckdb-filter-attribution-v1.0'
PLAN=I/'DUCKDB_FILTER_ATTRIBUTION_PLAN_v1.0.md'; DRIVER=I/'duckdb_topk_driver'; EDGE=I/'duckdb_topk_edge_test'
LIBS={'heap_stock':I/'artifacts/duckdb-v1.4.0-baseline','heap_scalar_specialized':I/'artifacts/duckdb-v1.4.0-heap_scalar_specialized','heap_avx2':I/'artifacts/duckdb-v1.4.0-heap_avx2'}
SOURCES={'heap_stock':None,'heap_scalar_specialized':I/'filter-attribution-v1.0/physical_top_n.heap_scalar_specialized.cpp','heap_avx2':I/'native-factorial-variants-v1.0/physical_top_n.heap_avx2.cpp'}
FIELDS=['dataset','kind','seed','block','variant_order','variant','rep','elapsed_ns','rows','checksum','cycles','instructions','branches','branch_misses','perf_running_pct']
SEED=7319042; BLOCKS=10; REPS=3

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def capture(args,env=None):
 p=subprocess.run(args,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode:raise RuntimeError(f'failed {args}\n{p.stderr}')
 return p.stdout.strip()
def datasets():
 out=[]; extra=DATA/'iid-replicates'
 for kind,orig in [('uniform',45),('normal',43),('pareto',44)]:
  xs=[DATA/f'{kind}_1000000_s{orig}.csv']+[extra/f'{kind}_1000000_s{s}.csv' for s in range(101,110)]
  if any(not x.is_file() for x in xs):raise RuntimeError(f'missing {kind} dataset')
  for p in xs:
   m=re.search(r'_s(\d+)\.csv$',p.name);out.append((p,kind,int(m.group(1))))
 nyc=DATA/'nyc_yellow_2024_01_distance_chrono_1000000.csv'
 if not nyc.is_file():raise RuntimeError('missing NYC stream')
 out.append((nyc,'nyc','fixed'));return out
def libpath(name):
 d=LIBS[name]; env=os.environ.copy();env['LD_LIBRARY_PATH']=str(d)
 o=capture(['ldd',str(DRIVER)],env); expected=str((d/'libduckdb.so.1.4').resolve())
 m=re.search(r'libduckdb\.so\.1\.4\s+=>\s+(\S+)',o)
 if not m or str(Path(m.group(1)).resolve())!=expected:raise RuntimeError('wrong runtime library: '+name+'\n'+o)
 return expected
def main():
 if OUT.exists():raise RuntimeError(f'result directory exists: {OUT}')
 for p in (PLAN,DRIVER,EDGE):
  if not p.is_file():raise RuntimeError(f'missing artifact {p}')
 if subprocess.run(['taskset','-c','2','true']).returncode:raise RuntimeError('CPU 2 unavailable')
 ds=datasets();OUT.mkdir(parents=True);(OUT/'logs').mkdir();(OUT/'plans').mkdir()
 variants={}
 for name,lib in LIBS.items():
  f=lib/'libduckdb.so.1.4'
  if not f.is_file():raise RuntimeError('missing library '+name)
  variants[name]={'resolved_library':libpath(name),'library_sha256':sha(f),'source_sha256':None if SOURCES[name] is None else sha(SOURCES[name])}
 manifest={'plan':str(PLAN),'plan_sha256':sha(PLAN),'runner':str(Path(__file__).resolve()),'runner_sha256':sha(Path(__file__).resolve()),'driver_sha256':sha(DRIVER),'edge_test_sha256':sha(EDGE),'variants':variants,'kernel':capture(['uname','-a']),'cpu':capture(['lscpu']),'python':sys.version,'platform':platform.platform(),'randomization_seed':SEED,'blocks_per_stream':BLOCKS,'timed_calls_per_process':REPS,'datasets':[{'path':str(p),'kind':k,'seed':s,'sha256':sha(p)} for p,k,s in ds],'started_unix':time.time(),'paired_blocks_completed':0}
 (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 records=[]; rng=random.Random(SEED)
 try:
  edge=[]
  for name,lib in LIBS.items():
   env=os.environ.copy();env['LD_LIBRARY_PATH']=str(lib)
   proc=subprocess.run([str(EDGE)],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   (OUT/f'edge_{name}.csv').write_text(proc.stdout);(OUT/'logs'/f'edge_{name}.stderr.txt').write_text(proc.stderr)
   if proc.returncode:raise RuntimeError(f'edge test failure {name}: {proc.stderr}')
   edge.append(proc.stdout.splitlines())
  if any(e!=edge[0] for e in edge):raise RuntimeError('edge hashes differ')
  manifest['edge_test_hashes']=edge[0]
  with (OUT/'timing.csv').open('x',newline='',encoding='utf-8') as tf,(OUT/'processes.jsonl').open('x',encoding='utf-8') as pf:
   w=csv.DictWriter(tf,fieldnames=FIELDS);w.writeheader();tf.flush()
   for path,kind,seed in ds:
    did=path.stem
    for block in range(1,BLOCKS+1):
     order=list(LIBS);rng.shuffle(order); checks={}
     for position,name in enumerate(order,1):
      plan=OUT/'plans'/f'{did}_block{block}_{name}.txt';env=os.environ.copy();env['LD_LIBRARY_PATH']=str(LIBS[name]);env['TOPK_VARIANT']=name
      cmd=['taskset','-c','2',str(DRIVER),str(path),'100',str(REPS),str(plan)]
      proc=subprocess.run(cmd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
      tag=f'{did}_block{block}_{name}';(OUT/'logs'/f'{tag}.stdout.csv').write_text(proc.stdout);(OUT/'logs'/f'{tag}.stderr.txt').write_text(proc.stderr)
      record={'dataset':did,'kind':kind,'seed':seed,'block':block,'variant_order':position,'variant':name,'command':cmd,'returncode':proc.returncode,'stdout_file':f'logs/{tag}.stdout.csv','stderr_file':f'logs/{tag}.stderr.txt','plan_file':f'plans/{plan.name}'}
      records.append(record);pf.write(json.dumps(record)+'\n');pf.flush()
      if proc.returncode:raise RuntimeError(f'process failed: {record}\n{proc.stderr}')
      rows=list(csv.DictReader(io.StringIO(proc.stdout)))
      if len(rows)!=REPS:raise RuntimeError(f'expected {REPS} calls for {tag}')
      for row in rows:
       if int(row['rows'])!=100:raise RuntimeError('wrong result cardinality')
       w.writerow({'dataset':did,'kind':kind,'seed':seed,'block':block,'variant_order':position,'variant':name,**{x:row[x] for x in FIELDS[6:]}})
      tf.flush()
      if not plan.is_file() or 'TOP_N' not in plan.read_text():raise RuntimeError('wrong/missing plan')
      checks[name]={'checksums':[r['checksum'] for r in rows],'plan_sha256':sha(plan)}
     if len({tuple(v['checksums']) for v in checks.values()})!=1 or len({v['plan_sha256'] for v in checks.values()})!=1:raise RuntimeError(f'paired checksum/plan mismatch: {did} block {block}')
     manifest['paired_blocks_completed']+=1
     if manifest['paired_blocks_completed']%10==0:
      (OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(f"completed {manifest['paired_blocks_completed']}/310 paired blocks",flush=True)
  manifest['status']='complete';manifest['finished_unix']=time.time()
 except Exception as e:
  manifest['status']='stopped';manifest['error']=repr(e);manifest['finished_unix']=time.time();raise
 finally:(OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('COMPLETE',OUT)
if __name__=='__main__':main()
