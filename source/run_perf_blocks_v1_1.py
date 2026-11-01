#!/usr/bin/env python3
"""Randomized independent PMU process blocks for v1.1 primary contrasts."""
import hashlib, json, random, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).parent
OUT=ROOT/"results/perf-blocks-v1.1-inline-avx"
DATA={
 "uniform":"data/uniform_1000000_s45.csv",
 "normal":"data/normal_1000000_s43.csv",
 "pareto":"data/pareto_1000000_s44.csv",
 "taxi":"data/nyc_yellow_2024_01_distance_chrono_1000000.csv",
}
METHODS=["heap_scalar","heap_avx2","array_scalar","array_avx2"]
SEED=20261120; BLOCKS=5; REPS=10
OUT.mkdir(parents=True,exist_ok=False)
(OUT/"plan.txt").write_text(
 "Exploratory replication to assess PMU reproducibility after the fixed v1.1 PMU matrix.\n"
 f"five process blocks per dataset/k, methods randomized within each block, seed={SEED}; "
 f"{REPS} gated calls per process; CPU=2; events cycles:u,instructions:u,branches:u,branch-misses:u.\n"
 "Primary contrasts only; no timing or source-branch attribution claims.\n")
events=[];rng=random.Random(SEED)
for dataset,rel in DATA.items():
 for k in (100,10000):
  for block in range(BLOCKS):
   order=METHODS.copy();rng.shuffle(order)
   for pos,method in enumerate(order):
    out=OUT/f"{dataset}-k{k}-b{block:02d}-{pos}-{method}"
    cmd=[sys.executable,str(ROOT/"perf_region.py"),str(ROOT/rel),"--method",method,
      "--k",str(k),"--reps",str(REPS),"--cpu","2","--perf",
      "/usr/lib/linux-tools/5.15.0-198-generic/perf","--out",str(out)]
    # This Python file is launched inside WSL, so call the helper directly.
    r=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=240)
    events.append({"dataset":dataset,"k":k,"block":block,"position":pos,
      "method":method,"cmd":cmd,"returncode":r.returncode,
      "stdout":r.stdout,"stderr":r.stderr})
    with (OUT/"runs.jsonl").open("a") as f:f.write(json.dumps(events[-1])+"\n")
    if r.returncode: raise SystemExit(f"perf block failed: {dataset} k={k} b={block} {method}: {r.stderr}")
print(f"completed {len(events)} independently launched PMU regions under {OUT}")
