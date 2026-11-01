# Analysis details for DuckDB filter attribution v1.0

Frozen 2026-10-26 before reviewing supplemental timing outcomes. This records the bootstrap PRNG parameter omitted from the experiment plan. It does not change workloads, comparisons, metrics, sample size, or stopping rule.

- Bootstrap PRNG: NumPy PCG64, seed 7319043.
- Replicates: 100,000.
- Resampling: sample 10 seeds with replacement; within each sampled seed, sample its 10 paired process blocks with replacement; average block log ratios within seed and then equally across sampled seeds.
- Report exponentiated mean log ratios and percentile limits at quantiles 0.002777777777777778 and 0.9972222222222222 (99.4444% interval).
- Apply the same family coverage to 3 pairwise contrasts across 3 synthetic populations (9 intervals). No equivalence claim from intervals containing one.
- NYC: paired block ratios, median and range only.

Implementation note before successful analysis: the first analysis invocation exposed a key-type mismatch between string block IDs read from CSV and integer block IDs in the plan. It produced no estimates. The parser was corrected to convert block IDs to integers; no input observations or estimands changed.
