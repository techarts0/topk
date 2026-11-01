#!/usr/bin/env python3
"""Frozen four-cell DuckDB native Top-N factorial confirmation."""

import csv
import hashlib
import io
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("*")
INTEGRATION = ROOT / "source/integration"
DATA = ROOT / "source/data"
DRIVER = INTEGRATION / "duckdb_topk_driver"
VARIANT_DIR = INTEGRATION / "native-factorial-variants-v1.0"
PLAN = INTEGRATION / "DUCKDB_NATIVE_FACTORIAL_PLAN_v1.0.md"
EDGE_TEST = INTEGRATION / "duckdb_topk_edge_test"
OUTPUT = ROOT / "source/results/duckdb-native-factorial-v1.0"
VARIANTS = {
    "heap_stock": INTEGRATION / "artifacts/duckdb-v1.4.0-baseline",
    "heap_avx2": INTEGRATION / "artifacts/duckdb-v1.4.0-heap_avx2",
    "array_scalar": INTEGRATION / "artifacts/duckdb-v1.4.0-array_scalar",
    "array_avx2": INTEGRATION / "artifacts/duckdb-v1.4.0-treatment",
}
SOURCE_FILES = {
    "heap_stock": None,
    "heap_avx2": VARIANT_DIR / "physical_top_n.heap_avx2.cpp",
    "array_scalar": VARIANT_DIR / "physical_top_n.array_scalar.cpp",
    "array_avx2": VARIANT_DIR / "physical_top_n.combined.cpp",
}
CSV_FIELDS = [
    "dataset", "kind", "seed", "block", "variant_order", "variant", "rep",
    "elapsed_ns", "rows", "checksum", "cycles", "instructions", "branches",
    "branch_misses", "perf_running_pct",
]
RANDOMIZATION_SEED = 20261027
BLOCKS = 5
TIMED_CALLS = 3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_capture(args, env=None):
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {args}\n{result.stderr}")
    return result.stdout.strip()


def datasets():
    found = []
    names = {"uniform": 45, "normal": 43, "pareto": 44}
    extra = DATA / "iid-replicates"
    for kind, original_seed in names.items():
        candidates = [DATA / f"{kind}_1000000_s{original_seed}.csv"]
        candidates.extend(extra / f"{kind}_1000000_s{seed}.csv" for seed in range(101, 110))
        if len(candidates) != 10 or any(not item.is_file() for item in candidates):
            raise RuntimeError(f"expected ten frozen {kind} data files: {candidates}")
        for item in candidates:
            match = re.search(r"_s(\d+)\.csv$", item.name)
            found.append((item, kind, int(match.group(1))))
    nyc = DATA / "nyc_yellow_2024_01_distance_chrono_1000000.csv"
    if not nyc.is_file():
        raise RuntimeError(f"missing fixed NYC stream: {nyc}")
    found.append((nyc, "nyc", "fixed"))
    return found


def resolved_library(lib_dir: Path) -> str:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(lib_dir)
    output = run_capture(["ldd", str(DRIVER)], env=env)
    expected = str((lib_dir / "libduckdb.so.1.4").resolve())
    match = re.search(r"libduckdb\.so\.1\.4\s+=>\s+(\S+)", output)
    if not match or str(Path(match.group(1)).resolve()) != expected:
        raise RuntimeError(f"driver resolved wrong DuckDB library for {lib_dir}:\n{output}")
    return expected


def main():
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite existing result directory: {OUTPUT}")
    if not DRIVER.is_file() or not EDGE_TEST.is_file() or not PLAN.is_file():
        raise RuntimeError("driver, edge-test binary, or frozen plan is missing")
    if not (VARIANT_DIR / "physical_top_n.combined.cpp").is_file():
        raise RuntimeError("combined source snapshot is missing")
    if subprocess.run(["taskset", "-c", "2", "true"]).returncode:
        raise RuntimeError("logical CPU 2 is not available for the frozen affinity protocol")

    all_data = datasets()
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "logs").mkdir()
    (OUTPUT / "plans").mkdir()

    libraries = {}
    for name, lib_dir in VARIANTS.items():
        if not (lib_dir / "libduckdb.so.1.4").is_file():
            raise RuntimeError(f"missing library for {name}: {lib_dir}")
        libraries[name] = {
            "resolved_path": resolved_library(lib_dir),
            "sha256": sha256(lib_dir / "libduckdb.so.1.4"),
            "source_sha256": None if SOURCE_FILES[name] is None else sha256(SOURCE_FILES[name]),
        }

    edge_hashes = {}
    for name, lib_dir in VARIANTS.items():
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = str(lib_dir)
        proc = subprocess.run([str(EDGE_TEST)], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (OUTPUT / f"edge_{name}.csv").write_text(proc.stdout, encoding="utf-8")
        (OUTPUT / "logs" / f"edge_{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        if proc.returncode:
            raise RuntimeError(f"edge correctness test failed for {name}: {proc.stderr}")
        edge_hashes[name] = proc.stdout.splitlines()
    first_edge = next(iter(edge_hashes.values()))
    if any(values != first_edge for values in edge_hashes.values()):
        raise RuntimeError("edge correctness hashes differ across factorial cells")

    manifest = {
        "plan": str(PLAN), "plan_sha256": sha256(PLAN),
        "runner": str(Path(__file__).resolve()), "runner_sha256": sha256(Path(__file__).resolve()),
        "driver": str(DRIVER), "driver_sha256": sha256(DRIVER),
        "edge_test": str(EDGE_TEST), "edge_test_sha256": sha256(EDGE_TEST),
        "variants": libraries,
        "kernel": run_capture(["uname", "-a"]),
        "cpu": run_capture(["lscpu"]),
        "python": sys.version,
        "platform": platform.platform(),
        "randomization_seed": RANDOMIZATION_SEED,
        "blocks_per_dataset": BLOCKS,
        "timed_calls_per_process": TIMED_CALLS,
        "datasets": [{"path": str(path), "kind": kind, "seed": seed, "sha256": sha256(path)}
                     for path, kind, seed in all_data],
        "edge_hashes": edge_hashes,
        "started_unix": time.time(),
    }
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    rng = random.Random(RANDOMIZATION_SEED)
    paired_blocks = []
    with (OUTPUT / "timing.csv").open("x", newline="", encoding="utf-8") as timing_file, \
            (OUTPUT / "processes.jsonl").open("x", encoding="utf-8") as process_file:
        writer = csv.DictWriter(timing_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        timing_file.flush()
        for data_path, kind, seed in all_data:
            dataset_id = data_path.stem
            for block in range(1, BLOCKS + 1):
                order = list(VARIANTS)
                rng.shuffle(order)
                observations = {}
                for position, variant in enumerate(order, start=1):
                    plan_path = OUTPUT / "plans" / f"{dataset_id}_block{block}_{variant}.txt"
                    env = os.environ.copy()
                    env["LD_LIBRARY_PATH"] = str(VARIANTS[variant])
                    env["TOPK_VARIANT"] = variant
                    command = ["taskset", "-c", "2", str(DRIVER), str(data_path),
                               "100", str(TIMED_CALLS), str(plan_path)]
                    proc = subprocess.run(command, env=env, text=True,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    log_tag = f"{dataset_id}_block{block}_{variant}"
                    (OUTPUT / "logs" / f"{log_tag}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
                    (OUTPUT / "logs" / f"{log_tag}.stdout.csv").write_text(proc.stdout, encoding="utf-8")
                    record = {
                        "dataset": dataset_id, "kind": kind, "seed": seed, "block": block,
                        "variant_order": position, "variant": variant, "command": command,
                        "returncode": proc.returncode, "stderr_file": f"logs/{log_tag}.stderr.txt",
                        "stdout_file": f"logs/{log_tag}.stdout.csv", "plan_file": f"plans/{plan_path.name}",
                    }
                    process_file.write(json.dumps(record) + "\n")
                    process_file.flush()
                    if proc.returncode:
                        raise RuntimeError(f"process failed: {record}\n{proc.stderr}")
                    rows = list(csv.DictReader(io.StringIO(proc.stdout)))
                    if len(rows) != TIMED_CALLS:
                        raise RuntimeError(f"expected {TIMED_CALLS} timing rows in {log_tag}, got {len(rows)}")
                    for row in rows:
                        if int(row["rows"]) != 100:
                            raise RuntimeError(f"unexpected result cardinality in {log_tag}: {row}")
                        writer.writerow({
                            "dataset": dataset_id, "kind": kind, "seed": seed, "block": block,
                            "variant_order": position, "variant": variant,
                            **{field: row[field] for field in CSV_FIELDS[6:]},
                        })
                        timing_file.flush()
                    if not plan_path.is_file() or "TOP_N" not in plan_path.read_text(encoding="utf-8"):
                        raise RuntimeError(f"expected TOP_N plan in {plan_path}")
                    observations[variant] = {
                        "checksums": [row["checksum"] for row in rows],
                        "plan_sha256": sha256(plan_path),
                    }
                expected_checksums = observations["heap_stock"]["checksums"]
                expected_plan = observations["heap_stock"]["plan_sha256"]
                for variant in VARIANTS:
                    if observations[variant]["checksums"] != expected_checksums:
                        raise RuntimeError(f"checksum mismatch for {dataset_id}, block {block}, {variant}")
                    if observations[variant]["plan_sha256"] != expected_plan:
                        raise RuntimeError(f"plan mismatch for {dataset_id}, block {block}, {variant}")
                paired_blocks.append({"dataset": dataset_id, "block": block, "status": "four-way-valid"})
                if len(paired_blocks) % 10 == 0:
                    print(f"completed {len(paired_blocks)}/155 four-way paired blocks", flush=True)
    manifest["finished_unix"] = time.time()
    manifest["four_way_blocks_completed"] = len(paired_blocks)
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "paired_block_status.json").write_text(json.dumps(paired_blocks, indent=2) + "\n", encoding="utf-8")
    print(f"COMPLETE: {len(paired_blocks)} four-way blocks; results at {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise

