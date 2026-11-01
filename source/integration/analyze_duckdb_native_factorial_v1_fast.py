#!/usr/bin/env python3
"""Vectorized, deterministic nested-bootstrap analysis for native DuckDB 2x2."""

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

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


def contrast_logs(values):
    """Return five log ratios, positive when the named numerator is faster."""
    h0, h1 = math.log(values["heap_stock"]), math.log(values["heap_avx2"])
    a0, a1 = math.log(values["array_scalar"]), math.log(values["array_avx2"])
    heap_filter = h0 - h1
    array_filter = a0 - a1
    return np.asarray((h0 - a1, heap_filter, h0 - a0, array_filter,
                       array_filter - heap_filter), dtype=np.float64)


def load_blocks():
    with (RESULTS / "timing.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    expected_rows = 31 * 5 * 4 * 3
    if len(rows) != expected_rows:
        raise RuntimeError(f"expected {expected_rows} timed rows, got {len(rows)}")

    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row["dataset"], row["kind"], str(row["seed"]), int(row["block"]))
        cell = row["variant"]
        if cell not in CELLS:
            raise RuntimeError(f"unknown cell {cell}")
        grouped[key][cell].append(row)

    blocks = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (dataset, kind, seed, block), cells in grouped.items():
        if set(cells) != set(CELLS) or any(len(cells[c]) != 3 for c in CELLS):
            raise RuntimeError(f"incomplete four-way block: {dataset}, {block}")
        checksums = {cell: tuple(r["checksum"] for r in cells[cell]) for cell in CELLS}
        if len({tuple(sorted(v)) for v in checksums.values()}) != 1:
            raise RuntimeError(f"checksum mismatch in {dataset}, block {block}")
        times = {cell: statistics.median(float(r["elapsed_ns"]) for r in cells[cell])
                 for cell in CELLS}
        timing_log = contrast_logs(times)
        event_log = {}
        for event in EVENTS:
            if any(any(r[event] == "NA" for r in cells[cell]) for cell in CELLS):
                event_log[event] = None
            else:
                medians = {cell: statistics.median(float(r[event]) for r in cells[cell])
                           for cell in CELLS}
                event_log[event] = contrast_logs(medians)
        blocks[kind][seed][dataset].append({
            "block": block, "times_ns": times,
            "contrast_logs": timing_log, "event_logs": event_log,
        })

    if sum(len(xs) for seeds in blocks.values() for datasets in seeds.values()
           for xs in datasets.values()) != 155:
        raise RuntimeError("expected 155 four-way paired blocks")
    for kind in ("uniform", "normal", "pareto"):
        if len(blocks[kind]) != 10:
            raise RuntimeError(f"expected ten seeds for {kind}")
        if any(len(next(iter(datasets.values()))) != 5 for datasets in blocks[kind].values()):
            raise RuntimeError(f"expected five blocks per seed for {kind}")
    return rows, blocks


def iid_analysis(blocks):
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    lower_q = (1.0 - CI_LEVEL) / 2.0
    upper_q = 1.0 - lower_q
    output = {}
    for kind in ("uniform", "normal", "pareto"):
        seeds = sorted(blocks[kind])
        per_seed = []
        for seed in seeds:
            only_dataset = next(iter(blocks[kind][seed].values()))
            per_seed.append(np.stack([b["contrast_logs"] for b in only_dataset]))
        # Shape: seed x paired process block x contrast.
        values = np.stack(per_seed)
        estimates = values.mean(axis=(0, 1))
        boot = np.empty((BOOTSTRAPS, len(CONTRASTS)), dtype=np.float64)
        # Batch the resampling to keep peak memory bounded. Within each draw,
        # sample seeds, then sample five paired process blocks in each selected seed.
        batch_size = 5_000
        for start in range(0, BOOTSTRAPS, batch_size):
            count = min(batch_size, BOOTSTRAPS - start)
            seed_ix = rng.integers(0, len(seeds), size=(count, len(seeds)))
            block_ix = rng.integers(0, values.shape[1],
                                    size=(count, len(seeds), values.shape[1]))
            sampled = values[seed_ix[:, :, None], block_ix]
            boot[start:start + count] = sampled.mean(axis=(1, 2))

        contrasts = {}
        for j, name in enumerate(CONTRASTS):
            contrasts[name] = {
                "geomean_ratio": float(np.exp(estimates[j])),
                "lower_familywise_ci": float(np.exp(np.quantile(boot[:, j], lower_q))),
                "upper_familywise_ci": float(np.exp(np.quantile(boot[:, j], upper_q))),
                "coverage": CI_LEVEL,
                "seed_count": len(seeds), "blocks_per_seed": int(values.shape[1]),
                "seed_effects": {seed: float(np.exp(values[i].mean(axis=0)[j]))
                                 for i, seed in enumerate(seeds)},
            }

        pmu = {}
        for event in EVENTS:
            event_blocks = [b for seed in seeds
                            for dataset in blocks[kind][seed].values()
                            for b in dataset if b["event_logs"][event] is not None]
            event_ratios = {
                name: float(np.exp(np.mean([b["event_logs"][event][j]
                                            for b in event_blocks])))
                for j, name in enumerate(CONTRASTS)
            } if event_blocks else {name: None for name in CONTRASTS}
            pmu[event] = {
                "available": len(event_blocks) == 50,
                "valid_blocks": len(event_blocks),
                "geomean_ratios": event_ratios,
            }
        output[kind] = {"contrasts": contrasts, "pmu": pmu}
    return output


def fixed_stream_analysis(blocks):
    stream_data = next(iter(blocks["nyc"]["fixed"].values()))
    output = {"stream": "fixed chronological NYC taxi",
              "paired_block_count": len(stream_data), "contrasts": {}}
    for j, name in enumerate(CONTRASTS):
        ratios = [float(np.exp(row["contrast_logs"][j])) for row in stream_data]
        output["contrasts"][name] = {
            "block_ratios": ratios, "median": statistics.median(ratios),
            "minimum": min(ratios), "maximum": max(ratios),
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
        "bootstrap_rng": "NumPy PCG64, vectorized hierarchical resampling",
        "numpy_version": np.__version__,
        "timing_call_count": 1860,
        "paired_four_way_block_count": 155,
        "iid": iid_analysis(blocks),
        "nyc_fixed_stream": fixed_stream_analysis(blocks),
    }
    (RESULTS / "analysis.json").write_text(json.dumps(result, indent=2) + "\n",
                                             encoding="utf-8")
    with (RESULTS / "factorial_summary.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["kind", "contrast", "geomean_ratio", "lower_familywise_ci",
                  "upper_familywise_ci", "coverage", "seed_count", "blocks_per_seed"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for kind, summary in result["iid"].items():
            for contrast, values in summary["contrasts"].items():
                writer.writerow({"kind": kind, "contrast": contrast, **{
                    field: values[field] for field in fields[2:]
                }})
    print(json.dumps({
        "analysis": str(RESULTS / "analysis.json"),
        "bootstrap_rng": result["bootstrap_rng"],
        "bootstrap_reps": BOOTSTRAPS,
        "iid": {kind: {name: [round(row["geomean_ratio"], 3),
                              round(row["lower_familywise_ci"], 3),
                              round(row["upper_familywise_ci"], 3)]
                       for name, row in summary["contrasts"].items()}
                for kind, summary in result["iid"].items()},
        "nyc": {name: round(row["median"], 3)
                for name, row in result["nyc_fixed_stream"]["contrasts"].items()},
    }, indent=2))


if __name__ == "__main__":
    main()
