# User识别准确度评估

## 快速开始

```bash
# 评估所有任务
python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output identify_evaluation/user_identification_results.json

# 评估特定任务范围
python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output results.json \
  --task-range 1-10

# 评估特定项目
python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output results.json \
  --project commons-csv
```

## 评估规则

- **修改的测试方法**: 按方法级别计算
- **删除的测试方法**: 按方法级别计算
- **新增的测试方法**: 按文件级别计算（每个文件只算1个，标记为`__FILE_LEVEL_ADD__`）

## 结果文件

### user_identification_results.json

JSON结构：
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
  "by_project": { ... },
  "by_type": { ... },
  "tasks": [
    {
      "task_id": 1,
      "project": "commons-csv",
      "type": "type1",
      "commit": "030fb8e3",
      "precision": 33.33,
      "recall": 50.0,
      "f1_score": 40.0,
      "tp": 1,
      "fp": 2,
      "fn": 1,
      "gt_total": 2,
      "user_total": 3,
      "details": {
        "gt_tests": {
          "src/test/java/.../Test.java": ["method1", "method2"]
        },
        "user_tests": { ... },
        "true_positives": { ... },
        "false_positives": { ... },
        "false_negatives": { ... }
      }
    }
  ]
}
```

**注意**: details中的测试用例已按文件分组，避免重复文件路径。

## 评估结果（60个任务）

### 总体指标
- Precision: 22.53%
- Recall: 46.40%
- F1 Score: 30.33%

### 按项目
- commons-csv: F1=27.90% (Precision=20.35%, Recall=44.31%)
- gson: F1=71.74% (Precision=76.74%, Recall=67.35%)

### 按类型
- Type1: F1=22.20% (Precision=14.06%, Recall=52.72%)
- Type2: F1=39.44% (Precision=36.32%, Recall=43.14%)

## 关键发现

1. **高误报率**: 77.5%的识别是误报（FP=863/1114）
2. **项目差异大**: gson表现优秀，commons-csv表现较差
3. **Type1困难**: Type1的Precision仅14.06%
4. **Recall尚可**: 能识别出46.40%的过时测试

## 指标说明

- **TP (True Positives)**: 正确识别的过时测试
- **FP (False Positives)**: 错误识别的（不是过时测试却被识别为过时）
- **FN (False Negatives)**: 遗漏的过时测试
- **Precision** = TP / (TP + FP) = 正确识别的 / 总识别数
- **Recall** = TP / (TP + FN) = 正确识别的 / 实际过时数
- **F1 Score** = 2 × Precision × Recall / (Precision + Recall)
