# OpenCode Baseline

Scripts and prompts for evaluating OpenCode (with various LLM backbones) on the TEBench test-evolution task.

## Layout

```
baseline/opencode/
├── README.md
├── scripts/
│   ├── batch_opencode_runner.py        # Single-backbone batch runner
│   ├── multi_model_runner.py           # Multi-backbone runner (paper Table 4)
│   ├── batch_evaluate_worktrees_from_csv.py
│   ├── evaluate_opencode_results.py    # Wraps update_evaluation.EvaluationOrchestrator
│   └── prompts.py
└── docs/
    └── MULTI_MODEL_GUIDE.md
```

## Single Backbone

```bash
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i  /path/to/worktree_records.xlsx \
  -o  /path/to/opencode_results \
  -m  myprovider/claude-sonnet-4-6 \
  --workers 2 --status ready
```

Key flags: `--projects`, `--types`, `--limit`, `--verbose`.

## Multiple Backbones (paper Table 4)

```bash
python baseline/opencode/scripts/multi_model_runner.py \
  --input  /path/to/worktree_records.xlsx \
  --output /path/to/multi_model_results \
  --models claude-sonnet-4-6 qwen-3.5 glm-5 kimi-k2.5 deepseek-v3.2 \
  --workers 2 --status ready
```

Each model gets its own isolated copy of every worktree under
`<output>/<model>/`. See `docs/MULTI_MODEL_GUIDE.md` for details.

## Evaluate Results

```bash
python baseline/opencode/scripts/evaluate_opencode_results.py \
  -r /path/to/multi_model_results/<model_name> \
  -w /path/to/worktree_records.xlsx \
  -p /path/to/defects4j-projects \
  -o evaluation_<model_name>.json --verbose
```

The wrapper delegates to `update_evaluation.EvaluationOrchestrator`, so the
metrics it produces match those used in the rest of the benchmark.

## Notes

- OpenCode modifications are not committed; they stay in the worktree so that
  the evaluation step can compare them against ground truth.
- Maven RAT / enforcer / checkstyle plugins are bypassed during evaluation
  builds (`-Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true`).
- The OpenCode command is invoked as
  `opencode run <prompt> --dir <worktree> -m <model> --format json`.
