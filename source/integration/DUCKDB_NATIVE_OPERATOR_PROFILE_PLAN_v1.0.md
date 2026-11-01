# DuckDB native Top-N operator-profile confirmation plan v1.0

Confirmatory protocol frozen: 2026-10-25 (Asia/Shanghai), before the full paired profile run.

The driver received an instrumentation smoke test on the 100,003-row Uniform seed-42 stream (one profiled call per cell). The smoke test verified one `TOP_N` node, equal plans, and equal result checksums; those timings are excluded from confirmatory analysis. It motivated no workload, cell, metric, or contrast changes.

## Purpose

The native four-cell timing experiment measures query execution and result consumption. This supplemental experiment records DuckDB's physical \`TOP_N\` operator timing from its profiling tree, separately from client-visible query elapsed time. The profiler adds instrumentation; these values are secondary evidence and do not replace the unprofiled paired factorial.

## Factorial cells

Use the same four DuckDB 1.4.0 libraries, source identities, query, schema, and optimizer-selected path as the frozen native factorial:

| Cell | Candidate maintenance | Boundary filtering |
|---|---|---|
| heap_stock | Original bounded min-heap | Original per-chunk vector boundary filter |
| heap_avx2 | Original bounded min-heap | Guarded AVX2 specialization |
| array_scalar | Ascending contiguous candidate array | Original per-chunk vector boundary filter |
| array_avx2 | Ascending contiguous candidate array | Guarded AVX2 specialization |

## Workloads and protocol

Use the same 30 synthetic streams (ten seeds each for Uniform, Normal, and Pareto($\alpha=2$), each with $N=1{,}000{,}000$) plus the fixed chronological NYC Yellow Taxi stream. Run five independent process blocks per stream. Randomize the four-cell order within each block using Python random seed 20261029 and pin each process to logical CPU 2.

Each fresh process loads data and creates the in-memory table before enabling standard query profiling. It performs one full-sort-checked warm-up and records three profiled query executions. For each timed call, record:

1. client elapsed time from query start through result extraction;
2. the DuckDB \`OPERATOR_TIMING\` value for the unique physical \`TOP_N\` node;
3. the root query \`LATENCY\` reported by the same profiling tree.

DuckDB profiling uses \`PRAGMA enable_profiling='no_output'\`; the C API profiling tree is read immediately after each query. Query inputs, table construction, planning, and warm-up are excluded. These profiling runs are analyzed separately from the unprofiled timing and PMU experiments.

## Correctness and plan gates

Every output is compared with a full-sort reference and records its row count and checksum. Every process must produce the same \`TOP_N\` plan, exactly one \`TOP_N\` profiling node, and complete profiling metrics. Any plan, output, profiling-tree, build identity, or process-status mismatch stops the run. No adverse observation is discarded or silently rerun.

## Inference

For each IID population, use the five prespecified cell contrasts from the native factorial: package, AVX2-on-heap, array-with-stock-filter, AVX2-on-array, and filter-by-representation interaction. Use the median of the three profiled query calls as each process-block observation. Resample ten seeds and then paired process blocks in 100,000 nested bootstrap replicates using NumPy PCG64 seed 20261030; report 99.6667% intervals across the 15 distribution-by-contrast family. Apply the same contrast definitions separately to \`TOP_N\` operator timing and root query latency. Report the fixed NYC stream descriptively by paired-block medians and ranges.

The operator metric is interpreted as DuckDB's reported physical-operator timing under profiling, not as an uninstrumented latency. The unprofiled native factorial remains the primary performance result.

## Artifacts

- Driver source: \`duckdb_topk_operator_profile.cpp\`.
- Run script: \`run_duckdb_native_operator_profile_v1.py\`.
- Four pinned libraries and source snapshots: \`artifacts/\` and \`native-factorial-variants-v1.0/\`.
- Results: \`../results/duckdb-native-operator-profile-v1.0/\`.
