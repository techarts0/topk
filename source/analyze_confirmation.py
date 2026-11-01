#!/usr/bin/env python3
"""Validate and analyze the fixed v1.0 confirmation matrix."""
import csv, json, math, random, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent / "results/confirm-v1"
DATASETS = ("uniform", "normal", "pareto", "taxi")
KS = (100, 10000)
METHODS = ("heap_scalar", "heap_batch", "heap_avx2", "array_scalar", "array_batch", "array_avx2", "stl")
PRIMARY = (("heap", "heap_scalar", "heap_avx2"), ("array", "array_scalar", "array_avx2"))
EXPECTED_BLOCKS, EXPECTED_REPS = 25, 5
BOOTSTRAPS, BOOT_SEED = 100_000, 20261029
ALPHA_PER_COMPARISON = 0.05 / 8

def fail(msg):
    raise SystemExit("VALIDATION FAILURE: " + msg)

def load_cell(dataset, k):
    folder = ROOT / f"{dataset}-k{k}"
    if not folder.is_dir(): fail(f"missing cell {dataset}, k={k}")
    env = json.loads((folder / "environment.json").read_text())
    if env.get("status") != "confirmatory": fail(f"wrong status in {folder}")
    if int(env["args"]["blocks"]) != EXPECTED_BLOCKS or int(env["args"]["reps"]) != EXPECTED_REPS:
        fail(f"wrong block/repetition count in {folder}")
    if int(env["args"]["k"]) != k or env["args"].get("diagnostic"):
        fail(f"wrong k or diagnostic timing in {folder}")
    timing = list(csv.DictReader((folder / "timings.csv").open()))
    expected_rows = EXPECTED_BLOCKS * len(METHODS) * EXPECTED_REPS
    if len(timing) != expected_rows: fail(f"expected {expected_rows} observations in {folder}, got {len(timing)}")
    by = defaultdict(list); checksums = defaultdict(set)
    for row in timing:
        method, block = row["method"], int(row["block"])
        if method not in METHODS: fail(f"unexpected method {method}")
        if int(row["n"]) != 1_000_000 or int(row["k"]) != k: fail("input dimensions mismatch")
        by[(block, method)].append(int(row["ns"]))
        checksums[block].add(row["checksum"])
    for block in range(EXPECTED_BLOCKS):
        if len(checksums[block]) != 1: fail(f"checksum mismatch in {dataset}, k={k}, block={block}")
        for method in METHODS:
            if len(by[(block, method)]) != EXPECTED_REPS: fail(f"bad repetitions {dataset}/{k}/{block}/{method}")
    runs = [json.loads(x) for x in (folder / "runs.jsonl").read_text().splitlines() if x.strip()]
    if len(runs) != EXPECTED_BLOCKS * len(METHODS) or any(r["returncode"] != 0 for r in runs):
        fail(f"failed or missing process in {folder}")
    medians = {(b, m): float(np.median(by[(b, m)])) for b in range(EXPECTED_BLOCKS) for m in METHODS}
    return env, by, medians

cells = {}
for d in DATASETS:
    for k in KS:
        cells[(d, k)] = load_cell(d, k)

raw_path = ROOT / "paired_block_observations.csv"
summary_path = ROOT / "primary_summary.csv"
secondary_path = ROOT / "secondary_descriptive.csv"
raw_rows, primary_rows, secondary_rows = [], [], []
rng = np.random.default_rng(BOOT_SEED)
for (dataset, k), (env, values, medians) in cells.items():
    for block in range(EXPECTED_BLOCKS):
        for method in METHODS:
            vals = values[(block, method)]
            raw_rows.append({"dataset": dataset, "k": k, "block": block, "method": method,
                             "call_ns": ";".join(map(str, vals)), "block_median_ns": medians[(block, method)]})
    for structure, scalar, avx in PRIMARY:
        log_ratios = np.log([medians[(b, scalar)] / medians[(b, avx)] for b in range(EXPECTED_BLOCKS)])
        point = float(np.exp(log_ratios.mean()))
        draws = rng.integers(0, EXPECTED_BLOCKS, size=(BOOTSTRAPS, EXPECTED_BLOCKS))
        boot = np.exp(log_ratios[draws].mean(axis=1))
        lo, hi = np.quantile(boot, [ALPHA_PER_COMPARISON/2, 1-ALPHA_PER_COMPARISON/2])
        primary_rows.append({"dataset": dataset, "k": k, "structure": structure,
            "contrast": f"{scalar}/{avx}", "paired_blocks": EXPECTED_BLOCKS,
            "geomean_speedup_ratio": point, "simultaneous_nominal_95_ci_low": float(lo),
            "simultaneous_nominal_95_ci_high": float(hi),
            "interval_excludes_1": bool(hi < 1 or lo > 1),
            "interpretation": "ratio > 1 favors AVX2; nominal Bonferroni-adjusted bootstrap interval"})
    for label, numerator, denominator in (
        ("heap_scalar/heap_batch", "heap_scalar", "heap_batch"),
        ("array_scalar/array_batch", "array_scalar", "array_batch"),
        ("heap_scalar/array_scalar", "heap_scalar", "array_scalar"),
        ("stl/heap_scalar", "stl", "heap_scalar"),
    ):
        rr = np.array([medians[(b, numerator)] / medians[(b, denominator)] for b in range(EXPECTED_BLOCKS)])
        secondary_rows.append({"dataset": dataset, "k": k, "contrast": label,
            "geomean_paired_ratio": float(np.exp(np.log(rr).mean())),
            "min_block_ratio": float(rr.min()), "max_block_ratio": float(rr.max()),
            "direction_gt_1_percent": float(100 * (rr > 1).mean()),
            "status": "descriptive secondary; no inferential claim"})

for path, rows in ((raw_path, raw_rows), (summary_path, primary_rows), (secondary_path, secondary_rows)):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(f"Validated all 8 cells, {len(raw_rows)} paired block-method observations; wrote {summary_path}")
for r in primary_rows:
    print(f"{r['dataset']:7s} k={r['k']:5d} {r['structure']:5s} ratio={r['geomean_speedup_ratio']:.3f} "
          f"nominal-adjusted CI=[{r['simultaneous_nominal_95_ci_low']:.3f},"
          f"{r['simultaneous_nominal_95_ci_high']:.3f}] excludes-1={r['interval_excludes_1']}")
