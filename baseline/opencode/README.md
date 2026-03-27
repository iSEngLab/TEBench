# OpenCode Baseline

This directory contains all OpenCode-related code, scripts, and documentation for evaluating OpenCode as a baseline method for test evolution tasks.

## 📁 Directory Structure

```
baseline/opencode/
├── README.md                    # This file
├── scripts/                     # Executable scripts
│   ├── batch_opencode_runner.py    # Batch execution script
│   ├── evaluate_opencode_results.py # Evaluation script
│   └── prompts.py                   # Prompt templates
└── docs/                        # Documentation
    ├── BATCH_OPENCODE_GUIDE.md         # Batch execution guide
    ├── EVALUATE_OPENCODE_RESULTS.md    # Evaluation guide
    ├── RUN_OPENCODE_COMMONS_CSV_GSON.md # Project-specific guide
    └── EVALUATION_FIX_SUMMARY.md       # Fix summary and status
```

## 🚀 Quick Start

### 1. Batch Execute OpenCode

Run OpenCode on multiple tasks in parallel:

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --verbose
```

### 2. Evaluate Results

Evaluate OpenCode execution results:

```bash
python baseline/opencode/scripts/evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \
  --verbose
```

## 📊 Evaluation Metrics

### Coverage Overlap (60% weight)
- Measures how well User modifications match GT modifications in coverage increment
- Formula: `|User增量 ∩ GT增量| / |GT增量|`

### Modification Score (40% weight)
- Based on Jaccard similarity, measures modification efficiency
- Formula: `Jaccard = |User ∩ GT| / |User ∪ GT|`

### Overall Score
- Formula: `0.6 × Coverage Overlap + 0.4 × Modification Score`

## 📚 Documentation

- **[BATCH_OPENCODE_GUIDE.md](docs/BATCH_OPENCODE_GUIDE.md)**: Comprehensive guide for batch execution
- **[EVALUATE_OPENCODE_RESULTS.md](docs/EVALUATE_OPENCODE_RESULTS.md)**: Detailed evaluation guide
- **[RUN_OPENCODE_COMMONS_CSV_GSON.md](docs/RUN_OPENCODE_COMMONS_CSV_GSON.md)**: Project-specific execution guide
- **[EVALUATION_FIX_SUMMARY.md](docs/EVALUATION_FIX_SUMMARY.md)**: Summary of fixes and current status

## 🔧 Scripts

### batch_opencode_runner.py

Batch execution script with parallel processing support.

**Key Features:**
- Parallel execution with configurable workers
- Automatic prompt generation based on commit type
- Progress tracking and logging
- Result aggregation and summary generation

**Parameters:**
- `-i, --input`: Input Excel file (worktree_records.xlsx)
- `-o, --output`: Output directory for results
- `--workers`: Number of parallel workers (default: 2)
- `--projects`: Filter by project names
- `--types`: Filter by commit types (type1, type2, type3)
- `--status`: Filter by status (ready, pending, etc.)
- `--limit`: Limit number of tasks (for testing)
- `--verbose`: Enable verbose logging

### evaluate_opencode_results.py

**这是一个包装器script**，用于将OpenCoderesult转换为 `evaluate.py` 的inputformat，然后调用 `evaluate.py` 的batchevaluate功能。

**重要description:**
- evaluate逻辑**完全使用** `evaluate.py` 中的 `EvaluationOrchestrator`
- 本script只负责：
  1. 从OpenCoderesultdirectory读取executeinformation
  2. 从worktree_records.xlsx提取GT commit
  3. 调用 `EvaluationOrchestrator.run_batch_evaluation()`
  4. 合并OpenCodeexecuteinformation到evaluateresult
- 确保evaluate指标与主evaluate框架完全一致

**Key Features:**
- Automatic GT commit extraction from worktree_records.xlsx
- Uses the same evaluation logic as `evaluate.py`
- Merges OpenCode execution info (duration, modified files) with evaluation results
- Comprehensive scoring using EvaluationOrchestrator

**Parameters:**
- `-r, --opencode-results`: OpenCode results directory
- `-w, --worktree-records`: worktree_records.xlsx file path
- `-p, --project-base`: Project base directory
- `-o, --output`: Output JSON file
- `--verbose`: Enable verbose logging

### prompts.py

Prompt template definitions for OpenCode.

**Available Prompts:**
- `SIMPLE_PROMPT`: Unified prompt for all commit types
- `get_prompt_for_type()`: Get prompt by commit type
- `format_task_prompt()`: Format prompt with task-specific information

## 🎯 Workflow

### Complete Workflow

1. **Prepare Dataset**
   ```bash
   # Generate worktrees using main pipeline
   python main.py --config config.yaml
   ```

2. **Execute OpenCode**
   ```bash
   # Test with 5 tasks
   python baseline/opencode/scripts/batch_opencode_runner.py \
     -i worktree_records.xlsx \
     -o opencode_results_test \
     --workers 2 \
     --limit 5 \
     --verbose
   ```

3. **Evaluate Results**
   ```bash
   python baseline/opencode/scripts/evaluate_opencode_results.py \
     -r opencode_results_test \
     -w worktree_records.xlsx \
     -p defects4j-projects \
     -o evaluation_results_test.json \
     --verbose
   ```

4. **Analyze Results**
   ```bash
   # View summary
   python3 -c "
   import json
   with open('evaluation_results_test.json') as f:
       data = json.load(f)
       scores = data['metadata']['average_scores']
       print(f'Coverage Overlap: {scores[\"avg_coverage_overlap\"]:.2%}')
       print(f'Modification Score: {scores[\"avg_modification_score\"]:.2%}')
       print(f'Overall Score: {scores[\"avg_overall_score\"]:.2%}')
   "
   ```

## 📈 Results

### Test Run (5 tasks)
- **Total Tasks**: 5
- **Successful**: 5
- **Average Duration**: 452.8 seconds/task
- **Projects**: commons-csv, gson
- **Types**: type1, type2

### Evaluation Status
- Evaluation script successfully fixed and running
- Maven RAT checks bypassed
- Coverage analysis integrated

## 🐛 Known Issues & Fixes

### Issue 1: Maven RAT License Check
- **Problem**: OpenCode generated files without license headers
- **Fix**: Added `-Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true` to Maven commands
- **Files Modified**:
  - `evaluation/executability_evaluator.py`
  - `evaluation/coverage_increment_analyzer.py`

### Issue 2: OpenCode Command Format
- **Problem**: Incorrect command format
- **Fix**: Changed from `opencode <prompt> --cwd` to `opencode run <prompt> --dir`

### Issue 3: Logger Initialization
- **Problem**: Logger used before initialization
- **Fix**: Moved logger initialization to beginning of `__init__`

## 🔄 Integration with Main Project

This baseline implementation integrates with the main TUBench evaluation framework:

- Uses `evaluation.EvaluationOrchestrator` for evaluation
- Reads from `worktree_records.xlsx` generated by main pipeline
- Outputs results compatible with main evaluation format
- Shares utilities from `utils/` directory

## 📝 Notes

- OpenCode modifications are NOT committed - they remain in worktrees for evaluation
- Parallel execution recommended for efficiency (workers=2)
- Evaluation requires compiled projects and test execution
- Results include both time efficiency and quality metrics

## 🎓 Citation

If you use this baseline in your research, please cite:

```bibtex
@inproceedings{tubench2026,
  title={TUBench: A Benchmark for Test Evolution},
  author={Your Name},
  booktitle={Conference},
  year={2026}
}
```
