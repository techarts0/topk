#!/usr/bin/env python3
"""Analyze the separately profiled DuckDB Top-N factorial."""

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "source/results/duckdb-native-operator-profile-v1.0"
BOOTSTRAPS = 100_000
BOOTSTRAP_SEED = 20261030
CI_LEVEL = 1.0 - 0.05 / 15.0
CELLS = ("heap_stock", "heap_avx2", "array_scalar", "array_avx2")
METRICS = ("elapsed_ns", "topn_operator_ns", "root_latency_ns")
CONTRASTS = (
    "package_heap_stock_over_array_avx2",
    "avx2_effect_on_heap",
    "array_effect_with_stock_filter",
    "avx2_effect_on_array",
    "filter_by_representation_interaction",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contrast_logs(values):
    h0, h1 = math.log(values["heap_stock"]), math.log(values["heap_avx2"])
    a0, a1 = math.log(values["array_scalar"]), math.log(values["array_avx2"])
    heap_filter = h0 - h1
    array_filter = a0 - a1
    return np.asarray((h0 - a1, heap_filter, h0 - a0, array_filter,
                       array_filter - heap_filter), dtype=np.float64)


def load_blocks():
    with (RESULTS / "timing.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    expected_rows = 31 * 5 * 4 * 3
    if len(rows) != expected_rows:
        raise RuntimeError(f"expected {expected_rows} timed rows, found {len(rows)}")

    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row["dataset"], row["kind"], str(row["seed"]), int(row["block"]))
        if row["variant"] not in CELLS:
            raise RuntimeError(f"unknown variant: {row['variant']}")
        grouped[key][row["variant"]].append(row)

    blocks = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (dataset, kind, seed, block), cells in grouped.items():
        if set(cells) != set(CELLS) or any(len(cells[cell]) != 3 for cell in CELLS):
            raise RuntimeError(f"incomplete profile block: {dataset}, {block}")
        for cell in CELLS:
            if {int(row["topn_nodes"]) for row in cells[cell]} != {1}:
                raise RuntimeError(f"expected one TOP_N node: {dataset}, {block}, {cell}")
            if len({row["checksum"] for row in cells[cell]}) != 1:
                raise RuntimeError(f"checksum changed within cell: {dataset}, {block}, {cell}")
            if len({row["rows"] for row in cells[cell]}) != 1:
                raise RuntimeError(f"row count changed within cell: {dataset}, {block}, {cell}")
        checksums = {cells[cell][0]["checksum"] for cell in CELLS}
        row_counts = {cells[cell][0]["rows"] for cell in CELLS}
        if len(checksums) != 1 or len(row_counts) != 1:
            raise RuntimeError(f"four-cell correctness mismatch: {dataset}, {block}")

        observations = {}
        for metric in METRICS:
            cell_values = {cell: statistics.median(float(row[metric]) for row in cells[cell])
                           for cell in CELLS}
            if any(value <= 0 for value in cell_values.values()):
                raise RuntimeError(f"nonpositive {metric}: {dataset}, {block}")
            observations[metric] = {
                "cell_values": cell_values,
                "contrast_logs": contrast_logs(cell_values),
            }
        blocks[kind][seed][dataset].append({"block": block, "metrics": observations})

    total = sum(len(items) for seeds in blocks.values()
                for datasets in seeds.values() for items in datasets.values())
    if total != 155:
        raise RuntimeError(f"expected 155 paired blocks, found {total}")
    for kind in ("uniform", "normal", "pareto"):
        if len(blocks[kind]) != 10:
            raise RuntimeError(f"expected ten {kind} seeds")
        if any(len(next(iter(datasets.values()))) != 5
               for datasets in blocks[kind].values()):
            raise RuntimeError(f"expected five blocks per {kind} seed")
    if len(blocks["nyc"]["fixed"]) != 1:
        raise RuntimeError("expected one fixed NYC stream")
    return blocks


def iid_analysis(blocks, metric, rng):
    lower_q = (1.0 - CI_LEVEL) / 2.0
    upper_q = 1.0 - lower_q
    output = {}
    for kind in ("uniform", "normal", "pareto"):
        seeds = sorted(blocks[kind])
        per_seed = []
        for seed in seeds:
            only_dataset = next(iter(blocks[kind][seed].values()))
            per_seed.append(np.stack([b["metrics"][metric]["contrast_logs"]
                                      for b in only_dataset]))
        values = np.stack(per_seed)  # seed x paired process block x contrast
        estimate = values.mean(axis=(0, 1))
        boot = np.empty((BOOTSTRAPS, len(CONTRASTS)), dtype=np.float64)
        batch_size = 5_000
        for start in range(0, BOOTSTRAPS, batch_size):
            count = min(batch_size, BOOTSTRAPS - start)
            seed_ix = rng.integers(0, len(seeds), size=(count, len(seeds)))
            block_ix = rng.integers(0, values.shape[1],
                                    size=(count, len(seeds), values.shape[1]))
            boot[start:start + count] = values[seed_ix[:, :, None], block_ix].mean(axis=(1, 2))

        contrasts = {}
        for j, name in enumerate(CONTRASTS):
            contrasts[name] = {
                "geomean_ratio": float(np.exp(estimate[j])),
                "lower_familywise_ci": float(np.exp(np.quantile(boot[:, j], lower_q))),
                "upper_familywise_ci": float(np.exp(np.quantile(boot[:, j], upper_q))),
                "coverage": CI_LEVEL,
                "seed_count": len(seeds),
                "blocks_per_seed": int(values.shape[1]),
                "seed_effects": {seed: float(np.exp(values[i].mean(axis=0)[j]))
                                 for i, seed in enumerate(seeds)},
            }
        output[kind] = contrasts
    return output


def fixed_stream_analysis(blocks, metric):
    stream = next(iter(blocks["nyc"]["fixed"].values()))
    result = {"paired_block_count": len(stream), "contrasts": {}}
    for j, name in enumerate(CONTRASTS):
        ratios = [float(np.exp(block["metrics"][metric]["contrast_logs"][j]))
                  for block in stream]
        result["contrasts"][name] = {
            "block_ratios": ratios,
            "median": statistics.median(ratios),
            "minimum": min(ratios),
            "maximum": max(ratios),
        }
    return result


def main():
    blocks = load_blocks()
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    result = {
        "plan": "DUCKDB_NATIVE_OPERATOR_PROFILE_PLAN_v1.0.md",
        "measurement_note": "Profiled metrics are secondary and instrumented; elapsed_ns includes result extraction.",
        "primary_interval_coverage": CI_LEVEL,
        "primary_family_size": 15,
        "bootstrap_reps": BOOTSTRAPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_rng": "NumPy PCG64, nested seed and paired-block resampling",
        "paired_four_way_block_count": 155,
        "timed_call_count": 1860,
        "metrics": {},
    }
    flat_rows = []
    for metric in METRICS:
        iid = iid_analysis(blocks, metric, rng)
        nyc = fixed_stream_analysis(blocks, metric)
        result["metrics"][metric] = {"iid": iid, "nyc_fixed_stream": nyc}
        for kind, contrasts in iid.items():
            for contrast, values in contrasts.items():
                flat_rows.append({"metric": metric, "kind": kind, "contrast": contrast,
                                  **{key: values[key] for key in (
                                      "geomean_ratio", "lower_familywise_ci",
                                      "upper_familywise_ci", "coverage", "seed_count",
                                      "blocks_per_seed")}})
    analysis_path = RESULTS / "analysis.json"
    summary_path = RESULTS / "operator_profile_summary.csv"
    analysis_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat_rows[0]))
        writer.writeheader()
        writer.writerows(flat_rows)
    manifest = {
        "plan": "DUCKDB_NATIVE_OPERATOR_PROFILE_PLAN_v1.0.md",
        "plan_sha256": sha256(ROOT / "source/integration/DUCKDB_NATIVE_OPERATOR_PROFILE_PLAN_v1.0.md"),
        "timing_csv_sha256": sha256(RESULTS / "timing.csv"),
        "analysis_script": Path(__file__).name,
        "analysis_script_sha256": sha256(__file__),
        "analysis_sha256": sha256(analysis_path),
        "summary_csv_sha256": sha256(summary_path),
        "bootstrap_reps": BOOTSTRAPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "numpy_version": np.__version__,
        "paired_four_way_blocks": 155,
        "profiled_calls": 1860,
        "familywise_interval_coverage": CI_LEVEL,
    }
    (RESULTS / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                    encoding="utf-8")
    print(json.dumps({
        "analysis": str(RESULTS / "analysis.json"),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "metrics": {metric: {
            kind: {name: [round(row["geomean_ratio"], 3),
                          round(row["lower_familywise_ci"], 3),
                          round(row["upper_familywise_ci"], 3)]
                   for name, row in contrasts.items()}
            for kind, contrasts in data["iid"].items()
        } for metric, data in result["metrics"].items()},
        "nyc_heap_stock_over_heap_avx2": {
            metric: round(result["metrics"][metric]["nyc_fixed_stream"]["contrasts"]
                          ["avx2_effect_on_heap"]["median"], 3)
            for metric in METRICS
        },
    }, indent=2))


if __name__ == "__main__":
    main()
