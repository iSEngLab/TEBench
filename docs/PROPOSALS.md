# Proposals

## Enhance Type2 Detection for Branch-Coverage Gaps

### Background
Commit `08f8c503` introduces a new null-check branch in
`org.apache.commons.cli.CommandLine.addArg`. In the current pipeline:

- V-0.5 (old tests + new code) passes, but only covers the non-null branch.
- V0 (new tests + new code) covers both branches.
- Line coverage does not decrease between V-1 and V-0.5, so Type2 is not
  triggered, and the commit is classified as Type3 (fallback).

This reveals a gap: **old tests may miss new branches without a line-coverage
drop**, so Type2 (test insufficiency) is not detected.

### Proposal
Augment Type2 detection with **branch-coverage deltas** on changed methods.

**Rule (additional Type2 signal):**

If all of the following hold:

1) V-0.5 build and tests pass  
2) Branch coverage is available for changed methods  
3) `branch_coverage(V0) - branch_coverage(V-0.5) >= threshold`  

Then classify as Type2 (or "Type2-branch" subtype).

### Rationale
This captures cases where new control-flow paths are introduced and only the
new tests exercise them. It matches the semantic intent of Type2 (tests lag
behind new behavior), even when line coverage remains unchanged.

### Optional Extension
Consider adding **mutation score deltas** for changed methods:

- Run lightweight mutation testing on changed methods
- If `mutation_score(V0) - mutation_score(V-0.5)` exceeds a threshold, treat as
  Type2 evidence

### Notes
- This proposal complements (does not replace) the existing line-coverage rule.
- It would reclassify `08f8c503` from Type3 to Type2 under the branch-coverage
  signal.

## Extend Type1 to Include Test-Compile Failures

### Background
Commit `0b115d5f` changes `HelpFormatter.Builder.setShowDeprecated` from
`BiFunction<String, Option, String>` to `Function<Option, String>`. In V-0.5
(new source + old tests), the old test code still passes a two-argument lambda
and fails during **test compilation** (not runtime). The pipeline records this
as `test=ERROR`, which currently bypasses Type1 and falls into Type3 (Scenario U).

### Proposal
Treat **test compilation failures** in V-0.5 as Type1 (execution error),
because old tests cannot even compile against the new API.

**Rule (Type1 extension):**

If V-0.5 test phase fails due to **testCompile** errors, classify as Type1
with a distinct subtype, e.g. `type1_test_compile_failure`.

### Rationale
From a testing-evolution perspective, a test-compile failure is a stronger
signal than a runtime failure: the old tests are *incompatible* with the new
API and cannot be executed at all. Classifying this as Type3 obscures the real
cause.

### Notes
- This does not change the existing Type1a (compile) / Type1b (runtime) logic.
- It simply adds a missing failure mode for V-0.5.

## Align Type2 Coverage Comparison with V0 vs V-0.5

### Background
Type2 is intended to measure whether **updated tests** (present in V0) improve
coverage over the **source-only** version (V-0.5). However, the current logic
compares V-0.5 against V-1, which measures a different concept (old tests vs
parent baseline) and can miss cases where new tests increase coverage.

### Proposal
Change Type2 detection to compare **V0 vs V-0.5** coverage on changed methods:

- `coverage_diff = coverage(V-0.5) - coverage(V0)`
- If the drop exceeds the threshold, classify as Type2.

### Rationale
This aligns the metric with the intended interpretation: V0 contains the
updated tests, so it is the correct reference for measuring whether old tests
in V-0.5 are insufficient for new code.
