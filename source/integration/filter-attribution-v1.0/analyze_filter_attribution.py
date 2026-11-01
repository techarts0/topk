#!/usr/bin/env python3
"""Nested paired analysis for the frozen 3-cell DuckDB filter attribution run."""
import csv,json,math,statistics,hashlib
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3]; R=ROOT/'source/results/duckdb-filter-attribution-v1.0'
OUT=R/'analysis.json'; REPS=100_000; RNG_SEED=7319043
CELLS=('heap_stock','heap_scalar_specialized','heap_avx2')
CONTRASTS=(('stock_over_scalar','heap_stock','heap_scalar_specialized'),('scalar_over_avx2','heap_scalar_specialized','heap_avx2'),('stock_over_avx2','heap_stock','heap_avx2'))
KINDS=('uniform','normal','pareto')

def boot(mat,rng):
 nseed,nblock=mat.shape
 si=rng.integers(0,nseed,size=(REPS,nseed))
 bi=rng.integers(0,nblock,size=(REPS,nseed,nblock))
 means=mat[si[:,:,None],bi].mean(axis=2).mean(axis=1)
 return float(np.exp(mat.mean())),float(np.exp(np.quantile(means,0.002777777777777778))),float(np.exp(np.quantile(means,0.9972222222222222)))
def main():
 if not (R/'run_manifest.json').is_file():raise RuntimeError('missing run manifest')
 manifest=json.loads((R/'run_manifest.json').read_text())
 if manifest.get('status')!='complete' or manifest.get('paired_blocks_completed')!=310:raise RuntimeError('experiment incomplete; refusing confirmatory analysis')
 with (R/'timing.csv').open(newline='') as f: rows=list(csv.DictReader(f))
 if len(rows)!=2790:raise RuntimeError(f'expected 2790 observations, got {len(rows)}')
 grouped=defaultdict(lambda:defaultdict(list))
 for row in rows:
  key=(row['kind'],row['seed'],row['block'],row['variant'])
  grouped[key]['time'].append(float(row['elapsed_ns']))
  for e in ('cycles','instructions','branches','branch_misses'):
   if row[e]!='NA' and float(row['perf_running_pct'])>=95:grouped[key][e].append(float(row[e]))
 blocks=defaultdict(dict)
 for (kind,seed,block,cell),values in grouped.items():
  if len(values['time'])!=3:raise RuntimeError('incomplete timed cell')
  blocks[(kind,seed,int(block))][cell]={k:statistics.median(v) for k,v in values.items() if v}
 if len(blocks)!=310 or any(set(v)!=set(CELLS) for v in blocks.values()):raise RuntimeError('incomplete paired cells')
 results={};rng=np.random.default_rng(RNG_SEED)
 for kind in KINDS:
  seeds=sorted({key[1] for key in blocks if key[0]==kind},key=int)
  if len(seeds)!=10:raise RuntimeError('expected ten seeds for '+kind)
  dres={'seed_ids':seeds,'n_seeds':len(seeds),'n_blocks':100,'contrasts':{},'pmu':{}}
  matrices={}
  for name,num,den in CONTRASTS:
   mat=np.empty((len(seeds),10),dtype=float)
   for i,seed in enumerate(seeds):
    for j,block in enumerate(range(1,11)):
     c=blocks[(kind,seed,block)]
     mat[i,j]=math.log(c[num]['time']/c[den]['time'])
   matrices[name]=mat
   est,lo,hi=boot(mat,rng)
   dres['contrasts'][name]={'ratio':est,'lower_familywise_95':lo,'upper_familywise_95':hi,'coverage_pct':99.4444444444,'log_ratio_seed_means':[float(x) for x in mat.mean(axis=1)]}
  for event in ('cycles','instructions','branches','branch_misses'):
   ev={}
   for name,num,den in CONTRASTS[:2]:
    mat=np.empty((len(seeds),10));available=True
    for i,seed in enumerate(seeds):
     for j,block in enumerate(range(1,11)):
      c=blocks[(kind,seed,block)]
      if event not in c[num] or event not in c[den]:available=False;continue
      mat[i,j]=math.log(c[num][event]/c[den][event])
    if available:
     ev[name]={'geomean_ratio':float(np.exp(mat.mean())),'n_seed_blocks':100}
    else:ev[name]={'geomean_ratio':None,'n_seed_blocks':0}
   dres['pmu'][event]=ev
  results[kind]=dres
 nyc=[]
 for b in range(1,11):
  c=blocks[('nyc','fixed',b)]
  nyc.append({'block':b,**{name:c[num]['time']/c[den]['time'] for name,num,den in CONTRASTS}})
 result={'plan_sha256':manifest['plan_sha256'],'run_manifest_sha256':hashlib.sha256((R/'run_manifest.json').read_bytes()).hexdigest(),'timing_rows':len(rows),'paired_blocks':len(blocks),'bootstrap_replicates':REPS,'bootstrap_seed':RNG_SEED,'family_intervals':9,'coverage_pct':99.4444444444,'distributions':results,'nyc_descriptive':{'blocks':nyc,'median':{name:statistics.median(x[name] for x in nyc) for name,_,_ in CONTRASTS},'range':{name:[min(x[name] for x in nyc),max(x[name] for x in nyc)] for name,_,_ in CONTRASTS}}}
 (R/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
 with (R/'summary.csv').open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['kind','contrast','ratio','lower_99.4444','upper_99.4444'])
  for kind,d in results.items():
   for name,x in d['contrasts'].items():w.writerow([kind,name,x['ratio'],x['lower_familywise_95'],x['upper_familywise_95']])
 print(json.dumps({k:{n:[round(x['ratio'],4),round(x['lower_familywise_95'],4),round(x['upper_familywise_95'],4)] for n,x in v['contrasts'].items()} for k,v in results.items()},indent=2))
 print('NYC',result['nyc_descriptive'])
if __name__=='__main__':main()
