# Multi-Model OpenCode Runner

`multi_model_runner.py` evaluates the TUBench task across several LLM backbones
in one invocation, using the OpenCode agent framework as the harness. This is
the script used in the TUBench paper to generate the seven LLM-based
configurations reported in Table 4 (one closed-source backbone via Claude Code,
one via Codex CLI, and five via OpenCode — including the four open-source
backbones Qwen3.5, GLM-5, Kimi-K2.5, and DeepSeek-V3.2).

## Why a separate script

`batch_opencode_runner.py` runs a single model end-to-end. The multi-model
runner builds on the same prompt policy (`baseline/shared_test_update_prompt.py`)
and the same OpenCode invocation pattern, but adds:

- **Per-model isolated worktrees.** Each model gets its own copy of every
  worktree under `<output>/<model>/worktrees/`, so parallel runs don't
  contaminate each other's diff state.
- **Per-model results aggregation.** Each model writes its own `results.json`
  plus a top-level `multi_model_summary.json` index.
- **Paper-aligned defaults.** The default `--models` list mirrors the
  open-source backbones used in the paper.

## Quick start

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

python baseline/opencode/scripts/multi_model_runner.py \
  --input  /path/to/worktree_records.xlsx \
  --output /path/to/multi_model_results \
  --models claude-sonnet-4-6 qwen-3.5 glm-5 kimi-k2.5 deepseek-v3.2 \
  --workers 2 \
  --status ready
```

The values passed via `--models` are forwarded verbatim to OpenCode as
`opencode run ... -m <model>`. They must match the `provider/model` identifiers
configured in your OpenCode setup (e.g. `myprovider/claude-sonnet-4-6`).

## Output layout

```
<output>/
├── multi_model_summary.json         # per-model totals
├── claude-sonnet-4-6/
│   ├── results.json                 # one entry per task
│   ├── logs/task_001.log ...        # raw OpenCode stdout/stderr
│   └── worktrees/<task_name>/...    # mutated worktree (kept for evaluation)
├── qwen-3.5/
│   └── ...
├── glm-5/
│   └── ...
└── ...
```

After the multi-model run finishes, evaluate each model with the existing
pipeline:

```bash
python baseline/opencode/scripts/evaluate_opencode_results.py \
  -r <output>/qwen-3.5 \
  -w worktree_records.xlsx \
  -p defects4j-projects \
  -o eval_qwen.json --verbose
```

## Useful flags

| Flag | Purpose |
|------|---------|
| `--limit N` | Smoke run on the first N tasks |
| `--projects commons-csv gson` | Restrict by project |
| `--types type1 type2` | Restrict by classification type |
| `--status ready` | Only `ready` rows are picked up by default |
| `--workers 4` | Parallel tasks per model (per-model copies are isolated) |
| `--timeout 1800` | Per-task wall-clock cap in seconds |
| `--opencode-cmd /opt/opencode/bin/opencode` | Override the executable path |

## Mapping to paper Table 4

| Paper configuration | How to reproduce |
|---|---|
| OpenCode (Claude Sonnet 4.6) | `--models claude-sonnet-4-6` |
| OpenCode (Qwen3.5)           | `--models qwen-3.5` |
| OpenCode (GLM-5)             | `--models glm-5` |
| OpenCode (Kimi-K2.5)         | `--models kimi-k2.5` |
| OpenCode (DeepSeek-V3.2)     | `--models deepseek-v3.2` |

Run them all in one shot by listing every backbone after `--models`. The other
two paper configurations (Claude Code on Sonnet 4.6, Codex CLI on ChatGPT 5.3
Codex) live under `baseline/claude-code/` and `baseline/codex/` respectively.
