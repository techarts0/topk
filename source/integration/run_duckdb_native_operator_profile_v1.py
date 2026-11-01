#!/usr/bin/env python3
"""Collect DuckDB TOP_N operator timing separately from client query latency."""

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

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "source/integration"
DATA = ROOT / "source/data"
DRIVER = INTEGRATION / "duckdb_topk_operator_profile"
VARIANT_DIR = INTEGRATION / "native-factorial-variants-v1.0"
PLAN = INTEGRATION / "DUCKDB_NATIVE_OPERATOR_PROFILE_PLAN_v1.0.md"
OUTPUT = ROOT / "source/results/duckdb-native-operator-profile-v1.0"
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
FIELDS = [
    "dataset", "kind", "seed", "block", "variant_order", "variant", "rep",
    "elapsed_ns", "topn_operator_ns", "root_latency_ns", "rows", "checksum", "topn_nodes",
]
RANDOMIZATION_SEED = 20261029
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
    originals = {"uniform": 45, "normal": 43, "pareto": 44}
    extra = DATA / "iid-replicates"
    for kind, original_seed in originals.items():
        candidates = [DATA / f"{kind}_1000000_s{original_seed}.csv"]
        candidates.extend(extra / f"{kind}_1000000_s{seed}.csv" for seed in range(101, 110))
        if len(candidates) != 10 or any(not item.is_file() for item in candidates):
            raise RuntimeError(f"expected ten frozen {kind} streams: {candidates}")
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
        raise RuntimeError(f"refusing to overwrite existing profile results: {OUTPUT}")
    if not DRIVER.is_file() or not PLAN.is_file():
        raise RuntimeError("operator-profile driver or frozen plan is missing")
    if subprocess.run(["taskset", "-c", "2", "true"]).returncode:
        raise RuntimeError("logical CPU 2 is unavailable for the paired protocol")

    streams = datasets()
    OUTPUT.mkdir(parents=True)
    (OUTPUT / "logs").mkdir()
    (OUTPUT / "plans").mkdir()
    libraries = {}
    for name, lib_dir in VARIANTS.items():
        lib = lib_dir / "libduckdb.so.1.4"
        if not lib.is_file():
            raise RuntimeError(f"missing library for {name}: {lib}")
        libraries[name] = {
            "resolved_path": resolved_library(lib_dir),
            "sha256": sha256(lib),
            "source_sha256": None if SOURCE_FILES[name] is None else sha256(SOURCE_FILES[name]),
        }
    manifest = {
        "plan": str(PLAN),
        "plan_sha256": sha256(PLAN),
        "runner": str(Path(__file__).resolve()),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "driver": str(DRIVER),
        "driver_sha256": sha256(DRIVER),
        "variants": libraries,
        "kernel": run_capture(["uname", "-a"]),
        "cpu": run_capture(["lscpu"]),
        "python": sys.version,
        "platform": platform.platform(),
        "randomization_seed": RANDOMIZATION_SEED,
        "blocks_per_stream": BLOCKS,
        "timed_calls_per_process": TIMED_CALLS,
        "datasets": [
            {"path": str(path), "kind": kind, "seed": seed, "sha256": sha256(path)}
            for path, kind, seed in streams
        ],
        "started_unix": time.time(),
    }
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    rng = random.Random(RANDOMIZATION_SEED)
    valid_blocks = []
    with (OUTPUT / "timing.csv").open("x", newline="", encoding="utf-8") as timing_file, \
            (OUTPUT / "processes.jsonl").open("x", encoding="utf-8") as process_file:
        writer = csv.DictWriter(timing_file, fieldnames=FIELDS)
        writer.writeheader()
        timing_file.flush()
        for data_path, kind, seed in streams:
            dataset_id = data_path.stem
            for block in range(1, BLOCKS + 1):
                order = list(VARIANTS)
                rng.shuffle(order)
                observations = {}
                for position, variant in enumerate(order, start=1):
                    plan_path = OUTPUT / "plans" / f"{dataset_id}_block{block}_{variant}.txt"
                    env = os.environ.copy()
                    env["LD_LIBRARY_PATH"] = str(VARIANTS[variant])
                    command = [
                        "taskset", "-c", "2", str(DRIVER), str(data_path),
                        "100", str(TIMED_CALLS), variant, str(plan_path),
                    ]
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
                        raise RuntimeError(f"profile process failed: {record}\n{proc.stderr}")
                    rows = list(csv.DictReader(io.StringIO(proc.stdout)))
                    if len(rows) != TIMED_CALLS:
                        raise RuntimeError(f"expected {TIMED_CALLS} profiled calls in {log_tag}, got {len(rows)}")
                    for row in rows:
                        if int(row["rows"]) != 100 or int(row["topn_nodes"]) != 1:
                            raise RuntimeError(f"invalid result/profile structure in {log_tag}: {row}")
                        if int(row["topn_operator_ns"]) <= 0 or int(row["root_latency_ns"]) <= 0:
                            raise RuntimeError(f"nonpositive profile timing in {log_tag}: {row}")
                        writer.writerow({
                            "dataset": dataset_id, "kind": kind, "seed": seed, "block": block,
                            "variant_order": position, "variant": variant,
                            **{field: row[field] for field in FIELDS[6:]},
                        })
                        timing_file.flush()
                    if not plan_path.is_file() or "TOP_N" not in plan_path.read_text(encoding="utf-8"):
                        raise RuntimeError(f"expected TOP_N plan in {plan_path}")
                    observations[variant] = {
                        "checksums": [row["checksum"] for row in rows],
                        "plan_sha256": sha256(plan_path),
                    }
                checksums = observations["heap_stock"]["checksums"]
                plan_hash = observations["heap_stock"]["plan_sha256"]
                for variant in VARIANTS:
                    if observations[variant]["checksums"] != checksums:
                        raise RuntimeError(f"checksum mismatch: {dataset_id}, block {block}, {variant}")
                    if observations[variant]["plan_sha256"] != plan_hash:
                        raise RuntimeError(f"plan mismatch: {dataset_id}, block {block}, {variant}")
                valid_blocks.append({"dataset": dataset_id, "block": block, "status": "four-way-valid"})
                if len(valid_blocks) % 10 == 0:
                    print(f"completed {len(valid_blocks)}/155 profiled blocks", flush=True)

    manifest["finished_unix"] = time.time()
    manifest["four_way_blocks_completed"] = len(valid_blocks)
    (OUTPUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "paired_block_status.json").write_text(json.dumps(valid_blocks, indent=2) + "\n", encoding="utf-8")
    print(f"COMPLETE: {len(valid_blocks)} profiled four-way blocks at {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise
