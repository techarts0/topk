#!/usr/bin/env python3
"""Seeded synthetic datasets or explicitly sourced real CSV columns; no dependencies."""
import argparse, csv, hashlib, json, math, platform, random
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--out',required=True)
    p.add_argument('--n',type=int,default=100000)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--kind',choices=['ranks','uniform','normal','pareto','ties','equal','increasing','decreasing','drift'],default='ranks')
    p.add_argument('--dtype',choices=['int32','float64'],default='int32')
    p.add_argument('--alpha',type=float,default=2.0)
    p.add_argument('--input',help='Optional real CSV; preserves source row order unless --shuffle')
    p.add_argument('--column',default='score')
    p.add_argument('--provenance',help='Required for real CSV: source/version/license description')
    p.add_argument('--shuffle',action='store_true')
    a=p.parse_args()
    if a.n<0 or a.alpha<=0: p.error('n >= 0 and alpha > 0 required')
    rng=random.Random(a.seed); meta=vars(a).copy()
    if a.input:
        if not a.provenance: p.error('--provenance required for imported data')
        values=[]
        with open(a.input,newline='') as f:
            for row in csv.DictReader(f):
                if len(values)>=a.n: break
                values.append(float(row[a.column]))
        meta['source_sha256']=sha(a.input)
        meta['kind']='real_import'
    elif a.kind=='ranks':
        values=list(range(a.n)); rng.shuffle(values)
    elif a.kind in ('uniform','normal','pareto'):
        if a.dtype!='float64': p.error('continuous distributions require float64; no implicit quantization')
        generator={'uniform':lambda:rng.random(),'normal':lambda:rng.gauss(0,1),'pareto':lambda:rng.paretovariate(a.alpha)}[a.kind]
        values=[generator() for _ in range(a.n)]
    elif a.kind=='ties': values=[rng.randrange(16) for _ in range(a.n)]
    elif a.kind=='equal': values=[7]*a.n
    elif a.kind=='increasing': values=list(range(a.n))
    elif a.kind=='decreasing': values=list(range(a.n,0,-1))
    else: values=[i//128+rng.randrange(256) for i in range(a.n)]
    if a.shuffle: rng.shuffle(values)
    if not all(math.isfinite(v) for v in values): p.error('nonfinite data: explicitly clean upstream')
    if a.dtype=='int32':
        if any(v!=int(v) or not -2**31<=v<2**31 for v in values): p.error('not exactly int32')
        values=list(map(int,values))
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists() or Path(str(out)+'.json').exists(): p.error('refusing to overwrite dataset/manifest')
    with out.open('w',newline='') as f:
        w=csv.writer(f); w.writerow(['score']); w.writerows((v,) for v in values)
    meta.update(n_actual=len(values),sha256=sha(out),python=platform.python_version(),
                duplicate_fraction=1-len(set(values))/len(values) if values else 0,
                generator_sha256=sha(__file__),status='prepared; not confirmatory data')
    Path(str(out)+'.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta))

if __name__=='__main__': main()
