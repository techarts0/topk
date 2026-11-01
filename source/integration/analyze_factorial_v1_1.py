#!/usr/bin/env python3
"""Analyze paired four-cell heap/array x scalar/AVX2 timing blocks."""
import csv
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
OUT = SOURCE / "results" / "factorial-v1.1"
BOOTSTRAPS = 100_000
BOOT_SEED = 20261026
CELLS = [(kind, k) for kind in ("uniform", "normal", "pareto")
         for k in (100, 10_000)]
CONTRASTS = ("package_array_avx2_over_heap_scalar",
             "array_scalar_over_heap_scalar",
             "heap_avx2_over_heap_scalar",
             "interaction_array_simd_vs_heap_simd")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def analyze_updates():
    path = SOURCE / "results" / "iid-replicates-v1.0" / "update_counts.csv"
    grouped = defaultdict(list)
    for row in read_rows(path):
        if row["structure"] == "heap":
            grouped[(row["kind"], int(row["k"]))].append(row)
    summaries = []
    for (kind, k), rows in sorted(grouped.items()):
        values = [int(row["updates"]) for row in rows]
        zs = [float(row["iid_z"]) for row in rows]
        if len(values) != 10:
            raise RuntimeError(f"expected ten seed diagnostics for {kind}, k={k}")
        summaries.append({"kind": kind, "k": k, "seed_count": len(values),
                          "mean_updates": statistics.mean(values),
                          "sd_across_seeds": statistics.stdev(values),
                          "min_updates": min(values), "max_updates": max(values),
                          "iid_expected": float(rows[0]["iid_mean"]),
                          "iid_theoretical_sd": float(rows[0]["iid_sd"]),
                          "mean_iid_z": statistics.mean(zs),
                          "max_abs_iid_z": max(map(abs, zs))})
    if len(summaries) != 6:
        raise RuntimeError(f"expected six update-count summaries, got {len(summaries)}")
    with (OUT / "update_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    return summaries


def verify_hashes():
    frozen = json.loads((OUT / "frozen_hashes.json").read_text())
    for rel, digest in frozen.items():
        path = SOURCE / rel
        if sha(path) != digest:
            raise RuntimeError(f"hash changed since timing freeze: {rel}")


def analyze():
    verify_hashes()
    update_summary = analyze_updates()
    raw = read_rows(OUT / "timing.csv")
    calls = defaultdict(list)
    for row in raw:
        key = (row["kind"], int(row["seed"]), int(row["k"]),
               int(row["block"]), row["method"])
        calls[key].append((int(row["rep"]), int(row["ns"]), row["checksum"]))

    block_times = {}
    for key, values in calls.items():
        if sorted(rep for rep, _, _ in values) != [0, 1, 2]:
            raise RuntimeError(f"incomplete triplicate: {key}")
        if len({checksum for _, _, checksum in values}) != 1:
            raise RuntimeError(f"within-process checksum mismatch: {key}")
        block_times[key] = statistics.median(ns for _, ns, _ in values)

    expected_seeds = {"uniform": {45, *range(101, 110)},
                      "normal": {43, *range(101, 110)},
                      "pareto": {44, *range(101, 110)}}
    block_effects = {}
    for kind, k in CELLS:
        seeds = sorted(expected_seeds[kind])
        for seed in seeds:
            for block in range(5):
                t = {m: block_times[(kind, seed, k, block, m)]
                     for m in ("heap_scalar", "heap_avx2", "array_scalar", "array_avx2")}
                package = math.log(t["heap_scalar"] / t["array_avx2"])
                array = math.log(t["heap_scalar"] / t["array_scalar"])
                heap_simd = math.log(t["heap_scalar"] / t["heap_avx2"])
                array_simd = math.log(t["array_scalar"] / t["array_avx2"])
                block_effects[(kind, k, seed, block)] = (
                    package, array, heap_simd, array_simd - heap_simd)

    point_logs = {}
    seed_logs = {}
    for kind, k in CELLS:
        for c, contrast in enumerate(CONTRASTS):
            per_seed = {}
            for seed in sorted(expected_seeds[kind]):
                values = [block_effects[(kind, k, seed, block)][c] for block in range(5)]
                per_seed[seed] = statistics.mean(values)
            seed_logs[(kind, k, contrast)] = per_seed
            point_logs[(kind, k, contrast)] = statistics.mean(per_seed.values())

    rng = random.Random(BOOT_SEED)
    distributions = {(kind, k, contrast): []
                     for kind, k in CELLS for contrast in CONTRASTS}
    for b in range(BOOTSTRAPS):
        for kind, k in CELLS:
            seeds = sorted(expected_seeds[kind])
            sampled_seed_logs = [0.0] * len(CONTRASTS)
            for _ in seeds:
                seed = seeds[rng.randrange(len(seeds))]
                block_values = [block_effects[(kind, k, seed, block)] for block in range(5)]
                block_sum = [0.0] * len(CONTRASTS)
                for _ in range(5):
                    values = block_values[rng.randrange(5)]
                    for c, value in enumerate(values):
                        block_sum[c] += value
                for c in range(len(CONTRASTS)):
                    sampled_seed_logs[c] += block_sum[c] / 5
            for c, contrast in enumerate(CONTRASTS):
                distributions[(kind, k, contrast)].append(sampled_seed_logs[c] / len(seeds))
        if (b + 1) % 25_000 == 0:
            print(f"bootstrap {b + 1}/{BOOTSTRAPS}", flush=True)

    summaries = []
    seed_rows = []
    for kind, k in CELLS:
        for c, contrast in enumerate(CONTRASTS):
            samples = distributions[(kind, k, contrast)]
            samples.sort()
            if c == 0:
                tail = 0.05 / (2 * 6)
                family = "six primary package contrasts"
            else:
                tail = 0.05 / (2 * 18)
                family = "eighteen secondary contrasts"
            lo = math.exp(samples[int(tail * BOOTSTRAPS)])
            hi = math.exp(samples[min(BOOTSTRAPS - 1,
                                      int((1 - tail) * BOOTSTRAPS))])
            estimate = math.exp(point_logs[(kind, k, contrast)])
            per_seed = seed_logs[(kind, k, contrast)]
            summaries.append({"contrast": contrast, "kind": kind, "k": k,
                              "seed_count": len(per_seed), "blocks_per_seed": 5,
                              "geomean_ratio": estimate, "lower_familywise_ci": lo,
                              "upper_familywise_ci": hi, "interval_coverage": 1 - 2 * tail,
                              "contrast_family": family, "bootstrap_reps": BOOTSTRAPS,
                              "bootstrap_seed": BOOT_SEED})
            for seed, log_effect in sorted(per_seed.items()):
                seed_rows.append({"contrast": contrast, "kind": kind, "k": k,
                                  "seed": seed, "paired_blocks": 5,
                                  "geomean_ratio": math.exp(log_effect)})
            print(f"{kind} k={k} {contrast}: {estimate:.4f} [{lo:.4f}, {hi:.4f}]",
                  flush=True)

    with (OUT / "factorial_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    with (OUT / "factorial_seed_effects.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(seed_rows[0]))
        writer.writeheader()
        writer.writerows(seed_rows)
    report = {"scope": "one WSL2 host, controlled C++ kernels, ten seeds per named distribution",
              "primary_contrast": "array_avx2 vs heap_scalar",
              "secondary_contrasts": list(CONTRASTS[1:]),
              "rank_dependence": "Uniform and Pareto data for matching seeds share underlying random.random draws and thus rank permutations; do not count them as independent rank-sequence replications.",
              "update_count_summary": update_summary, "summary": summaries,
              "warning": "Effects are conditional on this machine/compiler/kernel/data protocol and do not imply native database speedup."}
    (OUT / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    print(OUT / "analysis.json")


if __name__ == "__main__":
    analyze()
