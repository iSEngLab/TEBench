# TEBench: Benchmarking LLM Agents on Project-Level Test Evolution

TEBench is the first project-level benchmark for **test evolution** — the task of keeping a test suite synchronized with evolving production code. Given a project repository and a code-changing commit, TEBench requires systems to autonomously identify tests requiring modification, determine where new tests are needed, and produce the corresponding test patch.

TEBench curates **314 task instances from 10 real-world Java projects**, all drawn from the Defects4J ecosystem with developer-written ground truth. Each instance is classified into one or more of three evolution types.

## Evolution Types

| Type | Description |
|------|-------------|
| **Test-Breaking** | An existing test fails to compile or execute after the code change. The developer modifies it to restore correctness. |
| **Test-Stale** | An existing test still passes after the code change, but the developer updates it to better reflect the revised semantics. |
| **Test-Missing** | The developer adds a new test method to cover behavior introduced or exposed by the change. |

## Dataset Overview

| Project | Tasks | Src LOC | Test Files | Breaking | Stale | Missing |
|---------|-------|---------|------------|----------|-------|---------|
| commons-cli | 18 | 9,716 | 51 | 8 | 12 | 9 |
| commons-codec | 19 | 25,102 | 84 | 12 | 11 | 12 |
| commons-collections | 23 | 80,241 | 300 | 10 | 14 | 15 |
| commons-compress | 86 | 92,057 | 260 | 34 | 58 | 53 |
| commons-csv | 31 | 6,295 | 43 | 22 | 18 | 16 |
| commons-lang | 69 | 101,573 | 275 | 28 | 46 | 40 |
| commons-math | 8 | 142,903 | 403 | 8 | 3 | 2 |
| gson | 1 | 22,329 | 139 | 1 | 0 | 1 |
| jfreechart | 3 | 211,097 | 361 | 1 | 3 | 1 |
| jsoup | 56 | 27,390 | 84 | 48 | 42 | 50 |
| **Total** | **314** | **718,703** | **2,000** | **172** | **207** | **199** |

## Three-Version Structure

Each task instance is built around a three-version structure:

```
V-1  (parent commit — baseline before any changes)
  └──> V-0.5  (source code changes only, test files unchanged — agent input)
         └──> V0  (full commit with developer's test updates — ground truth)
```

- **V-1**: The parent commit, serving as the baseline.
- **V-0.5**: Only production code changes applied; test files are left unchanged. This is the state presented to the coding agent, simulating the real-world scenario where a developer has committed code changes but has not yet updated tests.
- **V0**: The full commit including the developer's actual test modifications, serving as ground truth.

## Benchmark Construction Pipeline

TEBench is constructed through a four-stage filtering pipeline over 17 Defects4J projects (67,670 commits):

1. **Project Source** — Start from Defects4J; exclude projects not using Maven (3 excluded).
2. **Static Filtering** — Date filter (post-2016/2019), co-modification of `src/main/` and `src/test/`, method-body-level AST changes via javalang. Reduces to **6,169 commits** from 14 projects.
3. **Execution-Based Validation** — Build two isolated versions per commit (V-0.5 and V0) using git worktree; run tests and collect JaCoCo coverage. Exclude build failures, non-functional test changes, and commits with unrelated test changes. Reduces to **561 commits** from 12 projects.
4. **Quality Filtering** — Exclude merge commits, constrain test change size to 5–200 lines, deduplicate by `(project, ClassName.methodName)`. Final dataset: **314 task instances** from **10 projects**.

## Evaluation Framework

### Identification Metrics

The identification stage measures whether the agent correctly locates tests requiring attention, compared against the developer ground truth:

- **Method-level granularity** for modified/deleted test methods: a true positive requires the agent to modify or delete the same test method as in the GT.
- **File-level granularity** for newly added test methods: a true positive requires the agent to add at least one new test method in the same file where the GT adds methods.

Reports **Precision**, **Recall**, and **F1**.

### Update Metrics

The update stage evaluates three dimensions:

**Executability** (`s_exec`):
```
0    — if compilation fails
0.5  — if compilation succeeds but tests fail
1    — if all tests pass
```

**Coverage Overlap** (`s_line`, `s_branch`): Measures how well the agent's tests cover the same lines/branches as the developer's GT tests, restricted to production methods modified by the commit.

**Modification Similarity** (`s_mod`): Token-level Jaccard similarity between agent's and GT test modifications.

**Composite Score**:
```
s_update = s_exec × (0.3·s_line + 0.3·s_branch + 0.4·s_mod)   if GT has coverage change
s_update = s_exec × s_mod                                        if GT has no coverage change
```

### Evaluation Results (from the paper)

All three evaluated coding agents (Claude Code, Codex CLI, OpenCode) converge on an identification F1 of **47–49%**, less than 2.5 percentage points apart. Test-Stale is the most challenging type (F1 ≈ 36%).

| System | Category | Base Model |
|--------|----------|------------|
| Heuristic Baseline | Static dependency analysis | — |
| Claude Code | Coding Agent | Claude Sonnet 4.6 |
| Codex CLI | Coding Agent | ChatGPT 5.3 Codex |
| OpenCode | Coding Agent | Claude Sonnet 4.6 |

## Repository Structure

```
TEBench/
├── config.py                           # Global configuration
├── main.py                             # Phase 1: dataset building / commit filtering
├── analysis.py                         # Phase 2: analysis tool entry point
├── generate_filtered_versions.py       # Phase 3: generate V-0.5 (filtered) branches
├── run_analysis.sh                     # Shell wrapper for batch project analysis
├── requirements.txt                    # Python dependencies
│
├── modules/                            # Core pipeline modules
│   ├── git_analyzer.py                 # Git operations
│   ├── code_analyzer.py                # Java AST parsing
│   ├── change_detector.py              # Method-level change detection
│   ├── maven_executor.py               # Maven build/test execution
│   ├── coverage_analyzer.py            # JaCoCo coverage analysis
│   ├── commit_filter.py                # Commit filtering logic
│   ├── dataset_generator.py            # Dataset export
│   ├── diff_filter.py                  # Source/test diff separation
│   ├── filtered_version_generator.py   # V-0.5 / T-0.5 branch generation
│   ├── isolated_executor.py            # Isolated worktree executor
│   └── commit_classifier.py            # Commit type classifier
│
├── analysis/                           # Analysis sub-package
│   ├── project_analyzer.py             # Per-project analysis orchestration
│   ├── commit_analyzer.py              # Per-commit analysis
│   ├── cache_manager.py                # Result caching
│   ├── report_generator.py             # JSON / Markdown report generation
│   ├── filter_commits.py               # Step 1: commit filtering script
│   ├── filter_commits_step2.py         # Step 2: fine-grained filtering
│   ├── classify_changes.py             # Step 3: evolution type classification
│   └── diagnose_projects.py            # Per-project elimination diagnostics
│
├── update_evaluation/                  # Update quality evaluation
│   ├── evaluation_orchestrator.py      # Evaluation orchestration
│   ├── executability_evaluator.py      # Compile + test pass evaluation
│   ├── coverage_increment_analyzer.py  # Coverage overlap analysis
│   ├── modification_effort_calculator.py # Modification similarity
│   ├── changed_method_extractor.py     # Changed method extraction
│   └── worktree_manager.py             # Worktree lifecycle management
│
├── identify_evaluation/                # Identification evaluation
│   ├── gt_extractor.py                 # Ground truth test change extractor
│   ├── example_predicted_format.json   # Example prediction format
│   └── README.md                       # Module documentation
│
├── baseline/                           # Baseline agent scripts
│   ├── claude-code/scripts/            # Claude Code runner
│   ├── codex/scripts/                  # Codex CLI runner
│   └── opencode/scripts/               # OpenCode runner
│
├── docs/                               # Additional documentation
│   ├── COMPATIBILITY.md
│   ├── PROPOSALS.md
│   └── WORKFLOW_GUIDE.md
│
└── example/                            # Sample analysis output
```

## Usage

### Prerequisites

- Python 3.8+
- Java 8+ (JDK)
- Maven 3.x
- Git

```bash
pip install -r requirements.txt
```

### Step 1: Configure

Edit `config.py` to set the repository path and filter parameters:

```python
class Config:
    REPO_PATH = "/path/to/your/java-project"
    DATE_FILTER = "2016-01-01"
    COVERAGE_THRESHOLD = 0.5
```

### Step 2: Initial Filtering (Static + Execution)

```bash
python main.py /path/to/java-project
```

Generates `output/dataset.json` containing all qualified commits.

### Step 3: Generate Filtered Versions (V-0.5)

```bash
python generate_filtered_versions.py output/dataset.json output/filtered_dataset.json
```

Creates `filtered/*` and `test-only/*` git branches for each qualified commit.

### Step 4: Analysis and Classification

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

### Step 5: Identification Evaluation

```bash
# Extract ground truth test changes
python identify_evaluation/gt_extractor.py \
  --input /path/to/worktree_records.csv \
  --output identify_evaluation/gt_changes_all.json
```

See `identify_evaluation/README.md` for full details.

### Step 6: Update Quality Evaluation

The `update_evaluation/` module evaluates agent output across executability, coverage overlap, and modification similarity. See the module source for the evaluation API.

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
| `quick` | File-level scan only — identify commits that co-modify test and source files |
| `method` | AST-level method change analysis — no test execution |
| `full` | Complete pipeline including isolated build, test execution, and JaCoCo coverage collection |

## Dependencies

```
GitPython==3.1.40
javalang==0.13.0
lxml==5.1.0
```

## Notes

1. **Repository state**: Ensure the Git repository is clean (no uncommitted changes) before running.
2. **JDK version**: Ensure a compatible JDK is installed for the target project.
3. **Maven**: Maven must be available on `PATH` or configured via `AnalysisConfig.MAVEN_EXECUTABLE`.
4. **Disk space**: Generated branches (`filtered/*`, `test-only/*`) consume additional disk space.
5. **Worktrees**: `analysis.py` uses temporary git worktrees that are automatically cleaned up.

### Cleaning Up Generated Branches

```bash
cd /path/to/your/java-project
git branch | grep "filtered/" | xargs git branch -D
git branch | grep "test-only/" | xargs git branch -D
```

## Research Applications

TEBench is designed to support research in:

- **Test evolution**: How test suites co-evolve with production code changes.
- **Automated test repair**: Detecting and fixing breaking or stale tests.
- **Test generation**: Producing new tests for uncovered behavior introduced by commits.
- **Coverage analysis**: Measuring coverage impact of code changes.
- **Coding agent evaluation**: Benchmarking LLM-based agents on project-level software engineering tasks.
