#!/usr/bin/env python3
"""Run paired four-cell heap/array x scalar/AVX2 timing blocks."""
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
DATA_ROOT = SOURCE / "data"
OUT = SOURCE / "results" / "factorial-v1.1"
EXE = SOURCE / "build" / "topk_bench"
KINDS = ("uniform", "normal", "pareto")
SEEDS = {"uniform": (45, *range(101, 110)),
         "normal": (43, *range(101, 110)),
         "pareto": (44, *range(101, 110))}
KS = (100, 10_000)
METHODS = ("heap_scalar", "heap_avx2", "array_scalar", "array_avx2")
BLOCKS = 5
REPS = 3


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def datasets():
    found = []
    for kind in KINDS:
        for seed in SEEDS[kind]:
            if seed in (45, 43, 44):
                path = DATA_ROOT / f"{kind}_1000000_s{seed}.csv"
            else:
                path = DATA_ROOT / "iid-replicates" / f"{kind}_1000000_s{seed}.csv"
            manifest_path = Path(str(path) + ".json")
            if not path.is_file() or not manifest_path.is_file():
                raise FileNotFoundError(f"missing dataset/manifest: {path}")
            manifest = json.loads(manifest_path.read_text())
            if (manifest.get("kind") != kind or manifest.get("seed") != seed
                    or manifest.get("n_actual") != 1_000_000
                    or manifest.get("dtype") != "float64"):
                raise RuntimeError(f"manifest mismatch: {manifest_path}")
            digest = sha(path)
            if digest != manifest.get("sha256"):
                raise RuntimeError(f"data hash mismatch: {path}")
            found.append((kind, seed, path, digest, sha(manifest_path)))
    return found


def freeze(items):
    files = [HERE / "FACTORIAL_TIMING_PLAN_v1.1.md",
             HERE / "REVISED_NARRATIVE_AND_NATIVE_PLAN_v1.0.md", Path(__file__),
             HERE / "analyze_factorial_v1_1.py", SOURCE / "data.py",
             SOURCE / "bench.cpp", SOURCE / "kernels.hpp", EXE,
             SOURCE / "build" / "command.txt", SOURCE / "build" / "version.txt",
             SOURCE / "results" / "iid-replicates-v1.0" / "update_counts.csv",
             SOURCE / "results" / "iid-replicates-v1.0" / "frozen_hashes.json"]
    for _, _, data_path, _, _ in items:
        files.extend((data_path, Path(str(data_path) + ".json")))
    manifest = {str(path.relative_to(SOURCE)): sha(path) for path in files}
    target = OUT / "frozen_hashes.json"
    if target.exists():
        if json.loads(target.read_text()) != manifest:
            raise RuntimeError("frozen source/data hash changed; preserve this run and do not continue")
    else:
        target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def run_one(path, method, k):
    command = [str(EXE), str(path), "float64", method, str(k), str(REPS)]

    def pin_child():
        os.sched_setaffinity(0, {2})

    result = subprocess.run(command, text=True, capture_output=True, check=True,
                            preexec_fn=pin_child)
    rows = list(csv.DictReader(result.stdout.splitlines()))
    if len(rows) != REPS or any(row["method"] != method for row in rows):
        raise RuntimeError(f"unexpected output for {command}")
    checksums = {row["checksum"] for row in rows}
    if len(checksums) != 1:
        raise RuntimeError(f"within-process checksum mismatch for {command}")
    return rows, result.stderr


def fail(item, exc):
    with (OUT / "failures.jsonl").open("a") as f:
        f.write(json.dumps({"item": item, "error": repr(exc), "time_unix": time.time()},
                           sort_keys=True) + "\n")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("validate", "run"):
        raise SystemExit("usage: run_factorial_v1_1.py validate|run")
    if not EXE.is_file():
        raise FileNotFoundError(EXE)
    items = datasets()
    if sys.argv[1] == "validate":
        version = subprocess.run([str(EXE), "--version"], text=True,
                                 capture_output=True, check=True).stdout.strip()
        if "avx2=1" not in version:
            raise RuntimeError(f"AVX2 unavailable or not reported by benchmark binary: {version}")
        self_test = subprocess.run([str(EXE), "--self-test"], text=True,
                                   capture_output=True, check=True).stdout.strip()
        if not self_test.startswith("PASS "):
            raise RuntimeError(f"benchmark self-test failed: {self_test}")
        print(f"validated {len(items)} datasets; no timing run started")
        print(version)
        print(self_test)
        return

    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "timing.csv"
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    freeze(items)
    cpu_model = "unknown"
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    (OUT / "environment.json").write_text(json.dumps({
        "platform": platform.platform(), "python": platform.python_version(),
        "cpu_model": cpu_model, "logical_cpu_count": os.cpu_count(),
        "available_affinity_before_pinning": sorted(os.sched_getaffinity(0)),
        "pinned_cpu": 2,
    }, indent=2) + "\n")
    rows = []
    order_rng = random.Random(20261025)
    total = len(items) * len(KS) * BLOCKS
    cell = 0
    for kind, seed, path, digest, manifest_digest in items:
        for k in KS:
            for block in range(BLOCKS):
                cell += 1
                order = list(METHODS)
                order_rng.shuffle(order)
                checksums = {}
                for order_index, method in enumerate(order):
                    item = {"kind": kind, "seed": seed, "k": k,
                            "block": block, "method": method, "order": order_index}
                    try:
                        calls, _ = run_one(path, method, k)
                    except Exception as exc:
                        fail(item, exc)
                        raise
                    checksums[method] = calls[0]["checksum"]
                    for call in calls:
                        rows.append({"kind": kind, "seed": seed, "dataset": path.name,
                                     "sha256": digest, "manifest_sha256": manifest_digest,
                                     "k": k, "block": block, "order": order_index,
                                     "method": method, "rep": int(call["rep"]),
                                     "cpu": 2,
                                     "command": json.dumps([str(EXE), str(path), "float64",
                                                            method, str(k), str(REPS)]),
                                     "ns": int(call["ns"]), "checksum": call["checksum"]})
                if len(set(checksums.values())) != 1:
                    exc = AssertionError(f"four-cell output mismatch: {checksums}")
                    fail({"kind": kind, "seed": seed, "k": k, "block": block}, exc)
                    raise exc
                print(f"paired block {cell}/{total}: {kind} seed={seed} k={k} block={block}",
                      flush=True)

    with target.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(target)


if __name__ == "__main__":
    main()
