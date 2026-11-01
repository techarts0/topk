# Filter attribution experiment: integrity and code-generation audit

Status: complete; 930 variant processes; 310 three-way paired blocks; 2790 timed calls.
Runtime event availability: 0 rows missing PMU; 0 rows below 95% running.
Edge-output hashes identical across all three libraries: True.

GCC Release optimization flags for the Unity translation unit: `-O3 -DNDEBUG -std=c++11 -fPIC`. For the scalar-specialized filter loop at source line 55, GCC vectorizer reports “couldn’t vectorize loop” because of control flow. The compiler did not auto-vectorize this loop in the tested build.

The explicit AVX2 diagnostic object contains YMM packed-double compare and mask instructions. In the saved disassembly, `vcmpgt_oqpd` count=1, `vcmpunordpd` count=1, and `vmovmskpd` count=1. These instruction counts are for the whole unity object and only establish code presence, not dynamic contribution.

Descriptive geometric-mean PMU event ratios (reference/treatment), computed from paired process medians:

| Input | Event contrast | Ratio |
|---|---|---:|
| uniform | cycles_stock_over_scalar | 3.8442 |
| uniform | cycles_scalar_over_avx2 | 1.0380 |
| uniform | instructions_stock_over_scalar | 5.3785 |
| uniform | instructions_scalar_over_avx2 | 1.3936 |
| uniform | branches_stock_over_scalar | 3.9332 |
| uniform | branches_scalar_over_avx2 | 1.7463 |
| uniform | branch_misses_stock_over_scalar | 1.3665 |
| uniform | branch_misses_scalar_over_avx2 | 0.9929 |
| normal | cycles_stock_over_scalar | 4.2591 |
| normal | cycles_scalar_over_avx2 | 1.0689 |
| normal | instructions_stock_over_scalar | 5.4247 |
| normal | instructions_scalar_over_avx2 | 1.4001 |
| normal | branches_stock_over_scalar | 3.9568 |
| normal | branches_scalar_over_avx2 | 1.7576 |
| normal | branch_misses_stock_over_scalar | 1.3558 |
| normal | branch_misses_scalar_over_avx2 | 1.0205 |
| pareto | cycles_stock_over_scalar | 4.2888 |
| pareto | cycles_scalar_over_avx2 | 1.0474 |
| pareto | instructions_stock_over_scalar | 5.4198 |
| pareto | instructions_scalar_over_avx2 | 1.3988 |
| pareto | branches_stock_over_scalar | 3.9552 |
| pareto | branches_scalar_over_avx2 | 1.7560 |
| pareto | branch_misses_stock_over_scalar | 1.3854 |
| pareto | branch_misses_scalar_over_avx2 | 0.9871 |

PMU ratios are descriptive. They do not attribute all instruction differences to one source-level operation. Full raw logs and the immutable run manifest are in the results directory.
