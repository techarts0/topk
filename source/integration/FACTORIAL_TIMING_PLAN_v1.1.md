# Factorial timing plan v1.1

Date: 2026-10-25 (Asia/Shanghai). This amendments the timing portion of `IID_REPLICATION_PLAN_v1.0.md` before any multi-seed timing run. It retains the ten-seed datasets and the already-collected diagnostic update counts. Version 1.0 timing is superseded and will not be run.

## Question and roles

Does the proposed joint treatment—sorted contiguous array plus AVX2 batch threshold filtering—improve the controlled Top-k kernel over the scalar bounded min-heap reference across the three generated continuous-IID populations and the tested k values? The heap/scalar cell is the only reference baseline. The other three cells are treatment/ablation variants, not industrial baselines.

Run the complete 2x2 factorial cells from `kernels.hpp`:

| Candidate structure | Scalar filter | AVX2 batch filter |
|---|---|---|
| Bounded min-heap | `heap_scalar` (reference) | `heap_avx2` (filter ablation) |
| Sorted contiguous array | `array_scalar` (structure ablation) | `array_avx2` (joint treatment) |

The experiment can estimate the package effect, component effects, and interaction for these kernels. It does not make the array an industry implementation and does not establish cache causality from timing alone.

## Workloads and protocol

- Use the ten existing deterministic seeds for each of Uniform, Normal, and Pareto(alpha=2), N=1,000,000, and k in {100, 10,000}. Use the original fixed NYC chronology only in the separately reported real-data/native-system checks; it is not a fourth IID population.
- Within each kind/seed/k, perform five independent process blocks. Randomize the order of all four cells within each block using Python `random.Random(20261025)`. Pin each process to logical CPU 2. Each process performs one correctness-checked warm-up and three timed calls. Input parsing and initialization remain outside the timed kernel interval, as in the existing benchmark.
- Preserve all three call times, process/block, randomized order, checksums, command, errors, data hashes, source hashes, compiler and binary identity. Require all four output checksums to match within each block.
- A block-level cell estimate is the median of the three calls. The paired block effect is a log time ratio. The seed estimate is the mean of its five paired block log ratios; the aggregate gives equal weight to each of ten seeds.
- Primary contrasts are the joint-treatment/reference ratios `heap_scalar / array_avx2` for each distribution at k=100 and k=10,000 (six contrasts). Use a 100,000-replicate nested bootstrap that resamples ten seeds, then five paired blocks within each sampled seed. Report 99.1667% percentile intervals (nominal 95% family coverage under Bonferroni across six primary contrasts).
- Secondary contrasts are `heap_scalar / array_scalar` (structure component), `heap_scalar / heap_avx2` (filter component), and the factorial interaction. Report their effect estimates and 99.7223% intervals (nominal 95% Bonferroni coverage across 18 distribution/k/secondary contrasts), or label the full secondary family exploratory if diagnostics invalidate its assumptions.

## Dependence and interpretation

The existing update-count diagnostics show that Uniform and Pareto values produced from a given seed have identical rank permutations because the generator uses the same underlying `random.random()` sequence and Pareto is a monotone transform. Report them as matched monotone-transform workloads, not independent rank-sequence replications. Normal follows a different draw path. Ten seeds per distribution are the resampling units; the three marginals are not three independent hardware populations.

The theory concerns accepted replacement counts, not time. Report the update counts, timing, and PMU results as distinct measurements. The primary package claim, if supported, is bounded to the tested kernels, N/k, generated workloads, compiler, CPU, and WSL2 environment. Do not infer that cache locality or SIMD individually caused the package result without the corresponding factorial contrasts and counter evidence.

## Integrity and stop rules

Write results to `source/results/factorial-v1.1/`, leaving v1.0 results unchanged. Freeze this plan, timing/analyzer scripts, kernel and benchmark sources/binary, build metadata, all input CSV/manifests, and the prior diagnostics hash before timing. Refuse to overwrite outputs. Preserve failures. Stop a cell on checksum mismatch, changed CPU affinity, changed input/source hashes, or missing paired blocks; do not silently rerun it. Complete timing only after the DuckDB baseline build stops, to avoid compile-time CPU contention.

