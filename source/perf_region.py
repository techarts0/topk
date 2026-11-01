#!/usr/bin/env python3
"""perf stat FIFO gating: excludes CSV load, reference sort, warmup and validation.
Counters sum timed selections, plus small timer/control-boundary overhead.
"""
import argparse, json, os, subprocess, tempfile, hashlib
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('data');p.add_argument('--method',default='heap_scalar');p.add_argument('--k',type=int,default=100)
p.add_argument('--reps',type=int,default=20);p.add_argument('--perf',required=True);p.add_argument('--out',required=True)
p.add_argument('--cpu',type=int)
a=p.parse_args();root=Path(__file__).resolve().parent
out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False)
fifo_dir=tempfile.TemporaryDirectory(prefix='topk-perf-',dir='/tmp')
ctl=Path(fifo_dir.name)/'control.fifo';ack=Path(fifo_dir.name)/'ack.fifo';os.mkfifo(ctl);os.mkfifo(ack)
data=Path(a.data).resolve();meta=json.loads(Path(str(data)+'.json').read_text())
if hashlib.sha256(data.read_bytes()).hexdigest()!=meta['sha256']: raise RuntimeError('dataset hash mismatch')
env=os.environ.copy();env.update(TOPK_PERF_CTL=str(ctl),TOPK_PERF_ACK=str(ack))
cmd=[a.perf,'stat','-D','-1','--control',f'fifo:{ctl},{ack}',
     '-e','cycles:u,instructions:u,branches:u,branch-misses:u','-x',';',
     '-o',str(out/'perf.csv'),'--',str(root/'build/topk_bench'),str(data),meta['dtype'],a.method,str(a.k),str(a.reps)]
if a.cpu is not None: cmd=['taskset','-c',str(a.cpu)]+cmd
(out/'command.json').write_text(json.dumps({'command':cmd,'scope':'sum of selected kernel calls + timer/control overhead; exploratory'},indent=2))
try:
    with (out/'timings.csv').open('w') as stdout, (out/'stderr.txt').open('w') as stderr:
        r=subprocess.run(cmd,env=env,stdout=stdout,stderr=stderr,timeout=180)
    (out/'status.json').write_text(json.dumps({'returncode':r.returncode}))
    if r.returncode: raise SystemExit('perf failed; inspect retained logs')
finally:
    ctl.unlink(missing_ok=True);ack.unlink(missing_ok=True)
    fifo_dir.cleanup()
