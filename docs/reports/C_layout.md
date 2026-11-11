# Part C completion checks

Code under test is the C layout engine on branch `c`, based on
main `94cd53d`. No `contracts.py` signature is changed; this work only adds
regression tests to `tests/test_layout.py` and module documentation.

Test date is 9 November 2026 in Asia/Hong_Kong.

Environment is Python 3.13.16, pytest 9.2.0 on Windows 11 (AMD64). libclang is
not installed on this machine, so the Clang-dependent source tests cannot run
locally; they report `DEPENDENCY_UNAVAILABLE` and are validated by the macOS CI
(macos-15, libclang 18.1.1). The C-owned `tests/test_layout.py` does not depend
on libclang and runs fully here. See `C_environment.json`.

| Commit | Input | Command | Expected | Actual | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 94cd53d | 9-token C-like set, circle/cat/code | `python -m pytest tests/test_layout.py -q` | One placement per token, in order | 23 passed | C_tests.txt | PASS |
| 94cd53d | 1200 width-1 tokens, CODE 178x32 | `test_code_mask_packs_tokens_across_many_short_spans` | Reach the fragmented rows (rows 4+, 5-8 short spans) and flow across spans | All 1200 placed; tokens occupy multi-span rows and cross spans | C_tests.txt | PASS |
| 94cd53d | Width-12 token, circle h=4 | `test_token_wider_than_base_spans_succeeds_after_growth` | Fail at h=4/5, succeed after growth to h=7 | 3 attempts, token in a 14-cell span, geometry PASS | C_tests.txt | PASS |
| 94cd53d | Width-801 token, limits 800x600 | `test_long_token_that_never_fits_raises_layout_limit_with_history` | Token wider than max_columns: LAYOUT_LIMIT with full history | LAYOUT_LIMIT, 12 attempts, all point at token 0 | C_tests.txt | PASS |
| 94cd53d | 60 tokens, circle h=6 | `test_growth_retries_until_the_tokens_fit` | Growth by 1.25, bounded, records failures then success | attempt_count > 1, last record success | C_tests.txt | PASS |
| 94cd53d | 200 tokens, max_columns=10 | `test_canvas_size_limit_raises_layout_limit` | Growth rejected at the column limit | LAYOUT_LIMIT, "canvas limits" reason | C_tests.txt | PASS |
| 94cd53d | Join checker sets the cancel event | `test_cancellation_in_join_checker_stops_layout` | Packing stops on cancellation | CANCELLED | C_tests.txt | PASS |
| 94cd53d | Slow checker, layout_timeout_s=0.001 | `test_layout_stage_timeout_raises_layout_timeout` | Stage timeout reported | LAYOUT_TIMEOUT with history | C_tests.txt | PASS |
| 94cd53d | Fake builder, 2s stage vs 100s pipeline | `test_mask_building_respects_layout_stage_budget` | Budget enforced during mask generation | Stops at 2s, not 10s | C_tests.txt | PASS |
| 94cd53d | Tokens a, b, +, c in 5 cells | `test_separator_resets_the_contiguous_run` | "a b+c" fits after run reset | 4 placements, gap at col 1 | C_tests.txt | PASS |
| 94cd53d | initial_scale=1.01, base 32 | `test_actual_scale_reflects_rounded_height` | Scale from rounded height | 33/32 = 1.03125 | C_tests.txt | PASS |

## Coverage of the assigned checks

| Assigned item | Where verified | Status |
| --- | --- | --- |
| Long tokens | width-12 growth test; width-801 impossible-canvas test | PASS |
| Multi-span layout | CODE 178x32 short-span test; cat multi-span geometry | PASS |
| Automatic growth (1.25, max 12) | growth and exhausted-attempt tests | PASS |
| Size limits (max_columns=800, max_rows=600) | canvas limit test | PASS |
| Timeout (layout_timeout_s) | stage timeout and shared-deadline tests | PASS |
| Cancellation (cancel_event) | join-checker cancellation test | PASS |
| Attempt history | success and failure histories asserted in every case | PASS |

## Known limits

- Packing is greedy in reading order, not globally optimal.
- A token wider than the largest span the canvas can provide cannot be split
  and always fails with `LAYOUT_LIMIT`.
- The local machine lacks libclang; the Clang-dependent suite is confirmed by
  CI rather than on this machine.
