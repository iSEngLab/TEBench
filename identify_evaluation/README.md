# Identification Evaluation

## Quick Start

```bash
# Evaluate all tasks
python evaluate_user_identification.py \
  --input /path/to/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output identify_evaluation/user_identification_results.json

# Evaluate a specific task range
python evaluate_user_identification.py \
  --input /path/to/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output results.json \
  --task-range 1-10

# Evaluate a specific project
python evaluate_user_identification.py \
  --input /path/to/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output results.json \
  --project commons-csv
```

## Granularity

- **Modified test methods**: counted at method level.
- **Deleted test methods**: counted at method level.
- **Added test methods**: counted at file level (one credit per file, marked as `__FILE_LEVEL_ADD__`).

## Output Format

`user_identification_results.json` contains:

```json
{
  "summary": {
    "total_tasks": 60,
    "total_gt_tests": 541,
    "total_user_tests": 1114,
    "true_positives": 251,
    "false_positives": 863,
    "false_negatives": 290,
    "precision": 22.53,
    "recall": 46.4,
    "f1_score": 30.33
  },
  "by_project": { },
  "by_type": { },
  "tasks": [
    {
      "task_id": 1,
      "project": "commons-csv",
      "type": "type1",
      "commit": "030fb8e3",
      "precision": 33.33,
      "recall": 50.0,
      "f1_score": 40.0,
      "tp": 1, "fp": 2, "fn": 1,
      "gt_total": 2, "user_total": 3,
      "details": {
        "gt_tests": { "src/test/java/.../Test.java": ["method1", "method2"] },
        "user_tests": { },
        "true_positives": { },
        "false_positives": { },
        "false_negatives": { }
      }
    }
  ]
}
```

Tests in `details` are grouped by file path to avoid duplicates.

## Metrics

- **TP (True Positives)** — correctly identified obsolete tests.
- **FP (False Positives)** — wrongly flagged tests (not actually obsolete).
- **FN (False Negatives)** — obsolete tests that were missed.
- **Precision** = `TP / (TP + FP)`
- **Recall** = `TP / (TP + FN)`
- **F1** = `2 · Precision · Recall / (Precision + Recall)`
