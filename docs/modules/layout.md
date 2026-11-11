# Module C — layout engine (`codeart/layout.py`)

C decides where every token of the analyzed source sits on B's fillable
:class:`~codeart.contracts.Mask`. It emits no source code and never mutates a
mask: it only produces one :class:`~codeart.contracts.Placement` per token and
records the lexical separators that must stay blank (`protected_blanks`).
D later writes the tokens at those placements and fills the remaining cells.

## Interface

```python
from codeart.layout import fit_layout

plan = fit_layout(
    model,       # SourceModel: tokens in order, plus the verification profile
    shape_spec,  # ShapeSpec: which pattern the mask is built for
    options,     # LayoutOptions: base height, growth, attempt/canvas/time limits
    mask_builder=build_mask,  # injected B builder returning a Mask
    join_checker=can_join,    # injected A checker for lexical separators
    ctx=ctx,                  # RunContext: cancellation and deadline
)
```

| type | fields used |
|---|---|
| `SourceModel` | `tokens` (`index`, `kind`, `spelling`, `width`), `profile` |
| `ShapeSpec` | the pattern kind passed to `mask_builder` |
| `LayoutOptions` | `base_height_rows`, `initial_scale`, `growth_factor`, `max_attempts`, `max_columns`, `max_rows`, `layout_timeout_s`, `font_metrics` |
| `Mask` | `width`, `height`, `allowed`, `spans` |
| `LayoutPlan` | `mask`, `placements`, `protected_blanks`, `actual_scale`, `attempt_count`, `attempt_history` |

## Packing rules

1. The mask's spans are flattened in reading order (row, then span start). A
   token is always placed inside a single span, so it never crosses a hole or a
   span edge.
2. A separator is added only when two tokens share a contiguous run and the
   injected `join_checker` forbids joining them. The blank is recorded in
   `protected_blanks`; the first token of each span starts a fresh run.
3. After a separator the contiguous run is reset to the current token. Directly
   joined tokens extend the run, so the checker always sees the real
   whitespace-free prefix.
4. When a token does not fit the current span, the engine moves to the next
   span without committing anything; when no span can hold it, the attempt
   fails and reports that token's index.

## Automatic growth

When an attempt fails, the engine asks the builder for a larger mask. The
requested height is
`ceil(base_height_rows * initial_scale * growth_factor ** attempt)`, with
`growth_factor = 1.25` and at most `max_attempts = 12` attempts. A grown mask
whose width exceeds `max_columns` (800) or height exceeds `max_rows` (600) is
rejected with `LAYOUT_LIMIT`.

`actual_scale` is the realized ratio `mask.height / base_height_rows`, computed
after height rounding, so a base of 32 rounded to 33 rows reports
`1.03125`, not the requested factor. Every attempt uses the same definition.

## Cancellation and time budgets

A single layout-stage deadline is derived once as
`min(clock + layout_timeout_s, ctx.deadline)` and is shared by all retries. A
`_LayoutContext` wraps the run context with that deadline and is passed to both
the mask builder and the packer, so the budget is enforced *during* mask
generation and on every token, not just between attempts.

- Explicit cancellation and the overall pipeline deadline are reported as
  `CANCELLED` / `PIPELINE_TIMEOUT` through the wrapped context.
- Running past the layout-stage deadline is reported as `LAYOUT_TIMEOUT`.
- Each attempt's `elapsed_s` covers both mask generation and token packing.

## Attempt history

Every attempt is recorded as an
:class:`~codeart.contracts.AttemptRecord` with `scale`, `width`, `height`,
`failure_token_index`, `reason` and `elapsed_s`. On success the records are
returned in `plan.attempt_history`; on failure they are attached to
`diagnostic.details["attempt_history"]`, including the interrupted attempt.

## Tests

`tests/test_layout.py` (23 tests) covers:

- one placement per token on circle, cat and code; placements stay in bounds,
  on allowed cells, non-overlapping and strictly ordered;
- protected blanks for tokens that cannot join, including two identifiers;
- bounded growth until the tokens fit, with failed and successful records;
- exhausted attempts and the canvas size limit, both raising `LAYOUT_LIMIT`;
- end-to-end render plus geometry check for base and grown plans;
- cancellation in the join checker, the stage timeout, the shared deadline
  across retries, the stage budget enforced during mask generation, and the
  elapsed time including packing;
- contiguous-run reset after a separator;
- the realized scale after rounded height;
- the fragmented 178x32 CODE mask flowing tokens across many short spans;
- a token wider than every base span succeeding only after growth;
- a token that can never fit raising `LAYOUT_LIMIT` with the full history.

## Known limits

- Placement is greedy in reading order; it does not search for a globally
  optimal packing, so a different ordering could in principle use fewer cells.
- A token wider than the largest span the canvas can provide cannot be placed
  and always fails with `LAYOUT_LIMIT`; growth cannot split a token.
- The engine only records placements; it cannot raise coverage itself, which is
  a consequence of the mask geometry and is completed by D's comment filling.
