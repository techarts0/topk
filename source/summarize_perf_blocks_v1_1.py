#!/usr/bin/env python3
"""Descriptive paired summaries of the randomized v1.1 PMU replication."""
import csv, json, math, statistics
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).parent/"results/perf-blocks-v1.1-inline-avx"
raw=[]
for d in sorted(x for x in ROOT.iterdir() if x.is_dir()):
    parts=d.name.rsplit("-",4)
    # names are dataset-kK-bBB-position-method; dataset may itself contain hyphens
    name=d.name
    import re
    m=re.match(r"^(.+)-k(\d+)-b(\d+)-\d+-(heap_scalar|heap_avx2|array_scalar|array_avx2)$",name)
    if not m: raise SystemExit(f"unparseable PMU cell {name}")
    dataset,k,block,method=m.group(1),int(m.group(2)),int(m.group(3)),m.group(4)
    ev={}
    for line in (d/"perf.csv").read_text().splitlines():
        p=line.split(";")
        if len(p)>=5 and p[0].strip().isdigit(): ev[p[2]]=(int(p[0]),float(p[4]))
    need=("cycles:u","instructions:u","branches:u","branch-misses:u")
    if any(e not in ev or ev[e][1]<99 for e in need): raise SystemExit(f"missing/low-running PMU event {name}")
    times=[int(r["ns"]) for r in csv.DictReader((d/"timings.csv").open())]
    if len(times)!=10: raise SystemExit(f"wrong reps in {name}")
    row={"dataset":dataset,"k":k,"block":block,"method":method,"median_ns":statistics.median(times)}
    for event,key in zip(need,("cycles","instructions","branches","branch_misses")):
        row[key]=ev[event][0]/len(times)
    row["branch_miss_pct"]=100*row["branch_misses"]/row["branches"]
    raw.append(row)
by={(r["dataset"],r["k"],r["block"],r["method"]):r for r in raw}
outrows=[]
for dataset in ("uniform","normal","pareto","taxi"):
 for k in (100,10000):
  for structure in ("heap","array"):
   pairs=[]
   for b in range(5):
    s=by[(dataset,k,b,structure+"_scalar")];v=by[(dataset,k,b,structure+"_avx2")]
    pairs.append({key:s[key]/v[key] for key in ("median_ns","cycles","instructions","branches","branch_misses")})
    pairs[-1]["branch_miss_pct_diff_pp"]=v["branch_miss_pct"]-s["branch_miss_pct"]
   row={"dataset":dataset,"k":k,"structure":structure,"paired_blocks":len(pairs)}
   for key in ("median_ns","cycles","instructions","branches","branch_misses"):
    ratios=[x[key] for x in pairs]
    row[key+"_scalar_over_avx2_geomean"]=math.exp(statistics.mean(math.log(x) for x in ratios))
    row[key+"_ratio_min"]=min(ratios);row[key+"_ratio_max"]=max(ratios)
    row[key+"_scalar_over_avx2_scalar_fewer_percent"]=100*sum(x<1 for x in ratios)/len(ratios)
   diffs=[x["branch_miss_pct_diff_pp"] for x in pairs]
   row["branch_miss_pct_AVX2_minus_scalar_pp_median"]=statistics.median(diffs)
   outrows.append(row)
rawfile=ROOT/"raw_summary.csv"
with rawfile.open("w",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(raw[0]));w.writeheader();w.writerows(raw)
outfile=ROOT/"paired_summary.csv"
with outfile.open("w",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(outrows[0]));w.writeheader();w.writerows(outrows)
print(f"Validated {len(raw)} PMU process regions; wrote {outfile}")
for r in outrows:
 print(f"{r['dataset']:7s} k={r['k']:5d} {r['structure']:5s} "
       f"perf-time S/AVX={r['median_ns_scalar_over_avx2_geomean']:.3f} "
       f"cycles={r['cycles_scalar_over_avx2_geomean']:.3f} "
       f"instructions={r['instructions_scalar_over_avx2_geomean']:.3f} "
       f"branch count={r['branches_scalar_over_avx2_geomean']:.3f} "
       f"miss count={r['branch_misses_scalar_over_avx2_geomean']:.3f} "
       f"AVX fewer cycles in {100-r['cycles_scalar_over_avx2_scalar_fewer_percent']:.0f}% blocks; "
       f"miss-rate change={r['branch_miss_pct_AVX2_minus_scalar_pp_median']:+.3f} pp")
