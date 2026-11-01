#!/usr/bin/env python3
"""Analyze the frozen DuckDB four-cell native factorial confirmation."""

import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "source/results/duckdb-native-factorial-v1.0"
BOOTSTRAPS = 100_000
BOOTSTRAP_SEED = 20261028
CI_LEVEL = 1.0 - 0.05 / 15.0
CELLS = ("heap_stock", "heap_avx2", "array_scalar", "array_avx2")
EVENTS = ("cycles", "instructions", "branches", "branch_misses")
CONTRASTS = (
    "package_heap_stock_over_array_avx2",
    "avx2_effect_on_heap",
    "array_effect_with_stock_filter",
    "avx2_effect_on_array",
    "filter_structure_interaction",
)


def percentile(values, q):
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def paired_log_contrasts(times):
    # Return log ratios; a positive value favors the numerator named in the plan.
    log_heap_filter = math.log(times["heap_stock"] / times["heap_avx2"])
    log_array_filter = math.log(times["array_scalar"] / times["array_avx2"])
    return {
        CONTRASTS[0]: math.log(times["heap_stock"] / times["array_avx2"]),
        CONTRASTS[1]: log_heap_filter,
        CONTRASTS[2]: math.log(times["heap_stock"] / times["array_scalar"]),
        CONTRASTS[3]: log_array_filter,
        CONTRASTS[4]: log_array_filter - log_heap_filter,
    }


def load_blocks():
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with (RESULTS / "timing.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 31 * 5 * 4 * 3:
        raise RuntimeError(f"expected 1860 timed rows, got {len(rows)}")
    for row in rows:
        key = (row["dataset"], row["kind"], str(row["seed"]), int(row["block"]))
        cell = row["variant"]
        if cell not in CELLS:
            raise RuntimeError(f"unknown cell {cell}")
        grouped[key][cell]["elapsed_ns"].append(float(row["elapsed_ns"]))
        grouped[key][cell]["checksum"].append(row["checksum"])
        for event in EVENTS:
            grouped[key][cell][event].append(None if row[event] == "NA" else float(row[event]))

    blocks = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (dataset, kind, seed, block), cells in grouped.items():
        if set(cells) != set(CELLS):
            raise RuntimeError(f"incomplete four-way block: {dataset}, {block}")
        checksums = {cell: cells[cell]["checksum"] for cell in CELLS}
        if len({tuple(v) for v in checksums.values()}) != 1:
            raise RuntimeError(f"output checksum mismatch in analysis: {dataset}, {block}")
        times = {cell: statistics.median(cells[cell]["elapsed_ns"]) for cell in CELLS}
        contrast_logs = paired_log_contrasts(times)
        event_logs = {}
        for event in EVENTS:
            values = [cells[cell][event] for cell in CELLS]
            if any(any(value is None for value in vector) for vector in values):
                event_logs[event] = None
            else:
                medians = {cell: statistics.median(cells[cell][event]) for cell in CELLS}
                event_logs[event] = paired_log_contrasts(medians)
        blocks[kind][seed][dataset].append({
            "block": block, "times_ns": times,
            "contrast_logs": contrast_logs, "event_logs": event_logs,
        })
    if sum(len(items) for by_seed in blocks.values() for by_data in by_seed.values() for items in by_data.values()) != 155:
        raise RuntimeError("expected 155 four-way paired blocks")
    for kind in ("uniform", "normal", "pareto"):
        if len(blocks[kind]) != 10:
            raise RuntimeError(f"expected ten seeds for {kind}")
        if any(len(next(iter(datasets.values()))) != 5 for datasets in blocks[kind].values()):
            raise RuntimeError(f"expected five process blocks per {kind} seed")
    return rows, blocks


def bootstrap_contrast(seed_map, contrast, rng):
    seeds = sorted(seed_map)
    sampled_seed_means = []
    for _ in seeds:
        seed = rng.choice(seeds)
        blocks = next(iter(seed_map[seed].values()))
        sampled_blocks = [rng.choice(blocks) for _ in blocks]
        sampled_seed_means.append(statistics.mean(
            block["contrast_logs"][contrast] for block in sampled_blocks
        ))
    return statistics.mean(sampled_seed_means)


def iid_analysis(blocks):
    rng = random.Random(BOOTSTRAP_SEED)
    output = {}
    lower_q = (1.0 - CI_LEVEL) / 2.0
    upper_q = 1.0 - lower_q
    for kind in ("uniform", "normal", "pareto"):
        seed_map = blocks[kind]
        contrasts = {}
        for contrast in CONTRASTS:
            per_seed = {}
            for seed in sorted(seed_map):
                sample_blocks = next(iter(seed_map[seed].values()))
                per_seed[seed] = statistics.mean(
                    row["contrast_logs"][contrast] for row in sample_blocks
                )
            estimate = math.exp(statistics.mean(per_seed.values()))
            boot = [bootstrap_contrast(seed_map, contrast, rng) for _ in range(BOOTSTRAPS)]
            contrasts[contrast] = {
                "geomean_ratio": estimate,
                "lower_familywise_ci": math.exp(percentile(boot, lower_q)),
                "upper_familywise_ci": math.exp(percentile(boot, upper_q)),
                "coverage": CI_LEVEL,
                "seed_count": len(per_seed),
                "blocks_per_seed": 5,
                "seed_effects": {seed: math.exp(value) for seed, value in per_seed.items()},
            }
        # PMU is secondary and descriptive. Report package ratios for the same 50 paired blocks.
        package_pmu = {}
        for event in EVENTS:
            values = [
                block["event_logs"][event][CONTRASTS[0]]
                for seed in seed_map
                for data in seed_map[seed].values()
                for block in data
                if block["event_logs"][event] is not None
            ]
            package_pmu[event] = {
                "available": len(values) == 50,
                "valid_blocks": len(values),
                "geomean_ratio_heap_stock_over_array_avx2": math.exp(statistics.mean(values)) if values else None,
            }
        output[kind] = {"contrasts": contrasts, "package_pmu": package_pmu}
    return output


def fixed_stream_analysis(blocks):
    data = next(iter(blocks["nyc"]["fixed"].values()))
    fields = {
        "package_heap_stock_over_array_avx2": CONTRASTS[0],
        "avx2_effect_on_heap": CONTRASTS[1],
        "array_effect_with_stock_filter": CONTRASTS[2],
        "avx2_effect_on_array": CONTRASTS[3],
        "filter_structure_interaction": CONTRASTS[4],
    }
    output = {"stream": "fixed chronological NYC taxi", "paired_block_count": len(data), "contrasts": {}}
    for name, key in fields.items():
        ratios = [math.exp(row["contrast_logs"][key]) for row in data]
        output["contrasts"][name] = {
            "block_ratios": ratios,
            "median": statistics.median(ratios),
            "minimum": min(ratios),
            "maximum": max(ratios),
        }
    return output


def main():
    _, blocks = load_blocks()
    result = {
        "plan": "DUCKDB_NATIVE_FACTORIAL_PLAN_v1.0.md",
        "primary_interval_coverage": CI_LEVEL,
        "primary_family_size": 15,
        "bootstrap_reps": BOOTSTRAPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "timing_call_count": 1860,
        "paired_four_way_block_count": 155,
        "iid": iid_analysis(blocks),
        "nyc_fixed_stream": fixed_stream_analysis(blocks),
    }
    (RESULTS / "analysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with (RESULTS / "factorial_summary.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = ["kind", "contrast", "geomean_ratio", "lower_familywise_ci",
                  "upper_familywise_ci", "coverage", "seed_count", "blocks_per_seed"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for kind, summary in result["iid"].items():
            for contrast, values in summary["contrasts"].items():
                writer.writerow({"kind": kind, "contrast": contrast, **{
                    field: values[field] for field in fields[2:]
                }})
    print(json.dumps({
        "analysis": str(RESULTS / "analysis.json"),
        "primary_interval_coverage": CI_LEVEL,
        "iid": {kind: {name: round(row["geomean_ratio"], 3)
                       for name, row in result["iid"][kind]["contrasts"].items()}
                for kind in result["iid"]},
        "nyc": {name: round(row["median"], 3)
                for name, row in result["nyc_fixed_stream"]["contrasts"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()

