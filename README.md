# Breaking, Stale, or Missing? Benchmarking Coding Agents on Project-Level Test Evolution

**Leaderboard:** <https://tebench-leadership.vercel.app/>
**Paper:** <https://arxiv.org/abs/2605.06125/>


TEBench is the first project-level benchmark for **test evolution** — the task of keeping a test suite synchronized with evolving production code. Given a project repository and a code-changing commit, TEBench requires systems to autonomously identify tests that need modification, determine where new tests are needed, and produce the corresponding test patch.

TEBench curates **314 task instances from 10 real-world Java projects**, all drawn from the Defects4J ecosystem with developer-written ground truth. Each instance is annotated with one or more of three evolution types.

## Evolution Types

| Type | Description |
|------|-------------|
| **Test-Breaking** | An existing test fails to compile or execute after the code change. The developer modifies it to restore correctness. |
| **Test-Stale** | An existing test still passes after the code change, but the developer updates it so it better reflects the revised semantics. |
| **Test-Missing** | The developer adds a new test method to cover behavior introduced or exposed by the change. |

Test-Breaking and Test-Stale together correspond to what prior work calls *obsolete tests*. Test-Missing extends the scope of the task beyond test repair to capture tests that need to be created from scratch in response to a commit.

## Dataset Overview

| Project | Tasks | Src LOC | Test Files | Breaking | Stale | Missing |
|---------|------:|--------:|-----------:|---------:|------:|--------:|
| commons-cli         | 18  |   9,716 |   51 |   8 |  12 |   9 |
| commons-codec       | 19  |  25,102 |   84 |  12 |  11 |  12 |
| commons-collections | 23  |  80,241 |  300 |  10 |  14 |  15 |
| commons-compress    | 86  |  92,057 |  260 |  34 |  58 |  53 |
| commons-csv         | 31  |   6,295 |   43 |  22 |  18 |  16 |
| commons-lang        | 69  | 101,573 |  275 |  28 |  46 |  40 |
| commons-math        |  8  | 142,903 |  403 |   8 |   3 |   2 |
| gson                |  1  |  22,329 |  139 |   1 |   0 |   1 |
| jfreechart          |  3  | 211,097 |  361 |   1 |   3 |   1 |
| jsoup               | 56  |  27,390 |   84 |  48 |  42 |  50 |
| **Total**           | **314** | **718,703** | **2,000** | **172** | **207** | **199** |

**Multi-label distribution.** 219 tasks (69.7%) carry multiple labels, and 45 tasks (14.3%) exhibit all three types simultaneously. The most frequent combination is Stale + Missing (105 tasks, 33.4%); only 95 tasks (30.3%) involve a single evolution type, confirming that real-world test evolution is predominantly multi-faceted.

**Task complexity.** The median task touches 4 changed files, 34 lines of source changes, and 32 lines of test changes. The distribution exhibits a long tail: the most complex task spans 20 files with 732 lines of source changes. 114 tasks (36.4%) involve modifications to more than one test file; 63 (20.1%) span multiple test packages; 236 (75.2%) require changes to more than one test method.

**Temporal distribution.** Commits span 2016 – 2025, with 77.4% from 2020 or later (39.8% from 2024 – 2025), so the dataset reflects contemporary development practices and coding conventions.

## Three-Version Structure

Each task instance is built around a three-version structure:

```
V-1   (parent commit — baseline before any changes)
  └──> V-0.5  (production-code changes only, test files unchanged — agent input)
         └──> V0    (full commit, including the developer's test updates — ground truth)
```

- **V-1** — the parent commit; serves as the baseline.
- **V-0.5** — only production-code changes applied; test files are left unchanged. This is the state the coding agent sees, simulating the real-world scenario in which a developer has committed code changes but has not yet updated the tests.
- **V0** — the full commit, including the developer's actual test modifications; serves as ground truth.

## Benchmark Construction Pipeline

TEBench is constructed through a four-stage filtering pipeline over 17 Defects4J projects (67,670 commits):

1. **Project Source** — Start from Defects4J; exclude 3 projects that do not use Maven, leaving 14 Maven-based projects (67,670 commits).
2. **Static Filtering** — Date filter (post-2016, post-2019 for Java 8+ projects), co-modification of `src/main/` and `src/test/`, method-body-level AST changes via `javalang`. Reduces to **6,169 commits** from 14 projects.
3. **Execution-Based Validation** — Build two isolated worktrees per commit (V-0.5 and V0), run the test suite, and collect line/branch coverage via JaCoCo. Exclude build failures, non-functional test changes, and commits whose test changes lack a verifiable causal relationship with the production change. Reduces to **561 commits** from 12 projects.
4. **Quality Filtering** — Exclude merge commits, constrain test-change size to 5 – 200 lines, and deduplicate by `(project, ClassName.methodName)`. Final dataset: **314 task instances** from **10 projects**.

## Evaluation Framework

### Identification Metrics

The identification stage measures whether the agent correctly locates the tests that require attention, compared against the developer ground truth:

- **Method-level granularity** for modified / deleted test methods: a true positive requires the agent to modify or delete the same test method as in the GT.
- **File-level granularity** for newly added test methods: a true positive requires the agent to add at least one new test method in the same file where the GT adds methods.

Reports **Precision**, **Recall**, and **F1**.

### Update Metrics

The update stage evaluates three dimensions, designed around the developer-written GT as a reference for evolution intent rather than as an absolute oracle.

**Executability** (`s_exec`):
```
0    — if compilation fails
0.5  — if compilation succeeds but tests fail
1    — if all tests pass
```

**Coverage Overlap** (`s_line`, `s_branch`): how well the agent's tests cover the same lines / branches as the GT tests, restricted to production methods modified by the commit:
```
s_line   = |C_line(agent)   ∩ C_line(gt)|   / |C_line(gt)|
s_branch = |C_branch(agent) ∩ C_branch(gt)| / |C_branch(gt)|
```

**Modification Similarity** (`s_mod`): token-level Jaccard similarity between agent and GT test modifications:
```
s_mod = |tokens(agent) ∩ tokens(gt)| / |tokens(agent) ∪ tokens(gt)|
```

**Composite Score**:
```
s_update = s_exec × (0.3·s_line + 0.3·s_branch + 0.4·s_mod)   if GT has coverage change
s_update = s_exec × s_mod                                       if GT has no coverage change
```

### Evaluated Systems (paper Table 4)

We evaluate eight systems organised along two axes: a heuristic baseline and seven LLM-based configurations spanning **three industrial agent frameworks** and **six base models**.

| Agent Framework | Base Model            | Version |
|---|---|---|
| Heuristic Baseline | —                  | —       |
| Claude Code        | Claude Sonnet 4.6  | v2.1.45 |
| Codex CLI          | ChatGPT 5.3 Codex  | v0.114.0 |
| OpenCode           | Claude Sonnet 4.6  | v1.2.16 |
| OpenCode           | Qwen3.5            | v1.2.16 |
| OpenCode           | GLM-5              | v1.2.16 |
| OpenCode           | Kimi-K2.5          | v1.2.16 |
| OpenCode           | DeepSeek-V3.2      | v1.2.16 |

OpenCode is the framework used to swap in the four open-source backbones (Qwen3.5, GLM-5, Kimi-K2.5, DeepSeek-V3.2) under an identical prompt and execution protocol. Use `baseline/opencode/scripts/multi_model_runner.py` to reproduce all OpenCode configurations in one invocation.

### Results Highlights (from the paper)

**Identification (Table 5).** All seven LLM-based configurations cluster within a 3.7-point F1 band overall (45.7 – 49.4%), with backbone variation contributing ≈ 3.6 F1 points and framework variation only ≈ 1.2 points. The bottleneck lies in the inherent task difficulty rather than in any specific configuration.

| Configuration         | Overall F1 | Breaking F1 | Stale F1 | Missing F1 |
|---|---:|---:|---:|---:|
| Heuristic Baseline    |  4.0 |  3.3 |  2.0 |  2.0 |
| Claude Code           | 47.1 | 59.6 | 35.0 | 54.1 |
| Codex CLI             | 49.4 | 69.4 | **37.4** | 54.5 |
| OpenCode (Sonnet)     | 48.3 | 66.8 | 35.6 | 51.2 |
| OpenCode (Qwen)       | 48.2 | 70.4 | 36.0 | **54.3** |
| OpenCode (GLM)        | 49.3 | 71.0 | 37.1 | 53.9 |
| OpenCode (Kimi)       | **49.4** | 60.7 | 35.8 | 51.3 |
| OpenCode (DeepSeek)   | 45.7 | 58.6 | 33.4 | 50.0 |

Test-Stale is the most challenging type (avg F1 ≈ 35.8%): stale tests still pass on the updated code, so no execution-failure signal is available, and configurations must rely on proactive semantic reasoning. Configurations exhibit a systematic Recall-over-Precision imbalance (mean gap 13.7 points), indicating a shared inductive bias toward over-prediction.

**Update (Table 6).** Composite update scores cluster within an 8.8-point band (63.6 – 72.3%). Executability stays consistently high (87.7 – 99.2%) yet exceeds modification similarity by 33.7 – 48.9 percentage points, indicating that producing executable tests is far easier than producing tests that align with developer intent.

| Configuration         | Overall OA | Breaking OA | Stale OA | Missing OA |
|---|---:|---:|---:|---:|
| Claude Code           | 70.5 | 73.2 | 68.5 | 63.8 |
| Codex CLI             | **72.3** | **76.6** | **70.8** | **65.7** |
| OpenCode (Sonnet)     | 68.9 | 73.8 | 65.4 | 62.6 |
| OpenCode (Qwen)       | 67.0 | 73.3 | 62.8 | 59.1 |
| OpenCode (GLM)        | 69.3 | 74.2 | 66.7 | 62.2 |
| OpenCode (Kimi)       | 63.6 | 68.3 | 59.8 | 56.0 |
| OpenCode (DeepSeek)   | 64.5 | 70.4 | 60.9 | 55.4 |

The type-wise difficulty ranking on the update task (Breaking > Stale > Missing) is the inverse of the identification ranking: once located, Breaking and Stale tests need only targeted assertion edits, whereas Missing requires generating entirely new code that naturally produces lower similarity to the GT.

## Repository Structure

```
TEBench/
├── config.py                           # Global configuration
├── main.py                             # Phase 1: dataset building / commit filtering
├── analysis.py                         # Phase 2: analysis tool entry point
├── generate_filtered_versions.py       # Phase 3: generate V-0.5 (filtered) branches
├── batch_worktree_builder.py           # Phase 4: bulk-build per-task worktrees
├── evaluate.py                         # Top-level evaluation entry point
├── evaluate_user_identification.py     # Identification-stage evaluation
├── extract_gt_changes.py               # GT extraction helper
├── compare_identification.py           # Per-config identification comparison
├── run_analysis.sh                     # Shell wrapper for batch project analysis
├── requirements.txt                    # Python dependencies
│
├── modules/                            # Core pipeline modules
│   ├── git_analyzer.py                 # Git operations
│   ├── code_analyzer.py                # Java AST parsing
│   ├── change_detector.py              # Method-level change detection
│   ├── maven_executor.py               # Maven build / test execution
│   ├── coverage_analyzer.py            # JaCoCo coverage analysis
│   ├── commit_filter.py                # Commit filtering logic
│   ├── dataset_generator.py            # Dataset export
│   ├── diff_filter.py                  # Source / test diff separation
│   ├── filtered_version_generator.py   # V-0.5 / T-0.5 branch generation
│   ├── isolated_executor.py            # Isolated worktree executor
│   └── commit_classifier.py            # Commit type classifier
│
├── analysis/                           # Analysis sub-package
│   ├── project_analyzer.py             # Per-project analysis orchestration
│   ├── commit_analyzer.py              # Per-commit analysis
│   ├── cache_manager.py                # Result caching
│   ├── report_generator.py             # JSON / Markdown report generation
│   ├── filter_commits.py               # Step 1 commit filtering
│   ├── filter_commits_step2.py         # Step 2 fine-grained filtering
│   ├── classify_changes.py             # Step 3 evolution-type classification
│   └── diagnose_projects.py            # Per-project elimination diagnostics
│
├── update_evaluation/                  # Update-quality evaluation
│   ├── evaluation_orchestrator.py      # Evaluation orchestration
│   ├── executability_evaluator.py      # Compile + test pass evaluation
│   ├── coverage_increment_analyzer.py  # Coverage overlap analysis
│   ├── modification_effort_calculator.py # Modification similarity (Jaccard)
│   ├── changed_method_extractor.py     # Changed method extraction
│   └── worktree_manager.py             # Worktree lifecycle management
│
├── identify_evaluation/                # Identification evaluation
│   ├── gt_extractor.py                 # Ground-truth test-change extractor
│   ├── example_predicted_format.json   # Example prediction format
│   └── README.md                       # Module documentation
│
├── baseline/                           # Coding-agent baselines (paper Table 4)
│   ├── shared_test_update_prompt.py    # Unified prompt across all agents
│   ├── claude-code/scripts/            # Claude Code runner
│   ├── codex/scripts/                  # Codex CLI runner
│   └── opencode/                       # OpenCode runners (5 backbones)
│       ├── README.md
│       └── scripts/
│           ├── batch_opencode_runner.py    # Single-backbone batch run
│           ├── multi_model_runner.py       # Multi-backbone runner (all 5 OpenCode configs)
│           ├── batch_evaluate_worktrees_from_csv.py
│           └── evaluate_opencode_results.py
```

## Usage

### Prerequisites

- Python 3.8+
- Java 8+ (JDK)
- Maven 3.x
- Git
- Optional: an [OpenCode](https://github.com/opencode-ai/opencode) install for the multi-backbone runner

```bash
pip install -r requirements.txt
```

### Step 1 — Configure

Edit `config.py` to set the repository path and filter parameters:

```python
class Config:
    REPO_PATH = "/path/to/your/java-project"
    DATE_FILTER = "2016-01-01"
    COVERAGE_THRESHOLD = 0.5
```

### Step 2 — Initial Filtering (Static + Execution)

```bash
python main.py /path/to/java-project
```

Generates `output/dataset.json` containing all qualified commits.

### Step 3 — Generate Filtered Versions (V-0.5)

```bash
python generate_filtered_versions.py output/dataset.json output/filtered_dataset.json
```

Creates `filtered/*` and `test-only/*` git branches for each qualified commit.

### Step 4 — Analysis and Classification

```bash
# Analyze a single project
python analysis.py --project /path/to/commons-csv

# Analyze all projects in a directory
python analysis.py --projects-dir /path/to/defects4j-projects --workers 4

# Quick scan (file-level only)
python analysis.py --project /path/to/project --phase quick

# Resume a previous run
python analysis.py --project /path/to/project --resume

# Filter by date
python analysis.py --project /path/to/project --since 2020-01-01
```

Output is written to `output/analysis/<project_name>/`.

### Step 5 — Run Coding Agents

The `baseline/` directory provides ready-to-use runners for the seven LLM-based configurations evaluated in the paper.

```bash
# Reproduce all five OpenCode rows of Table 4 in one invocation
python baseline/opencode/scripts/multi_model_runner.py \
  --input  /path/to/worktree_records.xlsx \
  --output /path/to/multi_model_results \
  --models claude-sonnet-4-6 qwen-3.5 glm-5 kimi-k2.5 deepseek-v3.2 \
  --workers 2 --status ready
```

The Claude Code and Codex CLI configurations live under `baseline/claude-code/` and `baseline/codex/` respectively. All three frameworks share the unified prompt in `baseline/shared_test_update_prompt.py`.

### Step 6 — Identification Evaluation

```bash
python identify_evaluation/gt_extractor.py \
  --input  /path/to/worktree_records.csv \
  --output identify_evaluation/gt_changes_all.json
```

See `identify_evaluation/README.md` for full details.

### Step 7 — Update-Quality Evaluation

```bash
python baseline/opencode/scripts/evaluate_opencode_results.py \
  -r /path/to/multi_model_results/<model_name> \
  -w /path/to/worktree_records.xlsx \
  -p /path/to/defects4j-projects \
  -o evaluation_<model_name>.json --verbose
```

`update_evaluation/evaluation_orchestrator.py` is the underlying engine and can also be called directly. It computes `s_exec`, `s_line`, `s_branch`, `s_mod`, and the composite `s_update` score per task.

## Dataset Format

### `filtered_dataset.json`

```json
{
  "metadata": {
    "source_dataset": "output/dataset.json",
    "total_processed": 130,
    "source_only": {
      "successful": 125,
      "failed": {"apply_patch": 0, "compilation": 5, "other": 0},
      "success_rate": "96.15%"
    },
    "test_only": {
      "successful": 123,
      "failed": {"apply_patch": 0, "compilation": 7, "other": 0},
      "success_rate": "94.62%"
    }
  },
  "commits": [
    {
      "original_commit": "d93c4940...",
      "parent_commit": "c36d6cde...",
      "author": "...",
      "date": "2025-03-15 04:29:53",
      "message": "...",
      "changed_files": {
        "test_files": ["..."],
        "source_files": ["..."],
        "other_files": []
      },
      "changed_methods": {
        "test_methods": [...],
        "source_methods": [...]
      },
      "coverage_analysis": {...},
      "filtered_version": {
        "success": true,
        "filtered_commit_hash": "ab0f7745...",
        "branch_name": "filtered/d93c4940"
      },
      "test_only_version": {
        "success": true,
        "test_only_commit_hash": "5e5d1c2a...",
        "branch_name": "test-only/d93c4940"
      }
    }
  ]
}
```

## Technical Implementation

### Diff Filtering Algorithm

The diff filter separates source and test changes from a single commit diff using regex-based parsing of the unified diff format:

1. Split diff by file (`diff --git` markers).
2. Classify each file as test (`src/test/`) or source (`src/main/`).
3. Reconstruct source-only and test-only patch files.
4. Apply patches independently to create V-0.5 and T-0.5 versions.

### Analysis Pipeline Phases

| Phase | Description |
|-------|-------------|
| `quick`  | File-level scan only — identify commits that co-modify test and source files |
| `method` | AST-level method-change analysis — no test execution |
| `full`   | Complete pipeline including isolated build, test execution, and JaCoCo coverage collection |

### Execution Environment

For each task instance we construct an isolated execution environment based on the V-0.5 version. We use Git's `worktree` mechanism to create a dedicated working directory that contains the updated source with the original tests; a separate worktree is attached to this branch. This provides full filesystem isolation between tasks while sharing only the read-only Git object store with the main repository — significantly more lightweight than provisioning a separate Docker container per project. A Docker image bundling all project environments and evaluation scripts is provided in the replication package for full reproducibility.

## Dependencies

```
GitPython==3.1.40
javalang==0.13.0
lxml==5.1.0
```

## Notes

1. **Repository state**: ensure the Git repository is clean (no uncommitted changes) before running.
2. **JDK version**: ensure a compatible JDK is installed for the target project.
3. **Maven**: must be available on `PATH` or configured via `AnalysisConfig.MAVEN_EXECUTABLE`.
4. **Disk space**: generated branches (`filtered/*`, `test-only/*`) and per-model worktree copies consume additional disk space.
5. **Worktrees**: `analysis.py` uses temporary git worktrees that are automatically cleaned up.

### Cleaning Up Generated Branches

```bash
cd /path/to/your/java-project
git branch | grep "filtered/"  | xargs git branch -D
git branch | grep "test-only/" | xargs git branch -D
```

## Research Applications

TEBench is designed to support research in:

- **Test evolution** — how test suites co-evolve with production code changes.
- **Automated test repair** — detecting and fixing breaking or stale tests.
- **Test generation** — producing new tests for uncovered behavior introduced by commits.
- **Coverage analysis** — measuring coverage impact of code changes.
- **Coding-agent evaluation** — benchmarking LLM-based agents on project-level software engineering tasks.

