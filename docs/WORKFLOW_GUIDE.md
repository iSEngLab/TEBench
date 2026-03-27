# TUBench 完整workflow程指南

本文档总结了 TUBench 从构建 worktree 到evaluateresult的完整流程。

## directory

1. [environment准备](#environment准备)
2. [构建 Worktree](#构建-worktree)
3. [execute OpenCode](#execute-opencode)
4. [提取 GT data](#提取-gt-data)
5. [evaluateresult](#evaluateresult)
6. [clean up资源](#clean up资源)

---

## environment准备

### directory结构

```
/Users/mac/Desktop/TestUpdate/
├── TUBench/                          # 主projectdirectory
│   ├── batch_worktree_builder.py     # Worktree batch构建工具
│   ├── extract_gt_changes.py         # GT data提取工具
│   ├── evaluate_user_identification.py  # identify准确度evaluate
│   └── baseline/opencode/scripts/
│       ├── batch_opencode_runner.py  # OpenCode batchexecute
│       └── batch_evaluate_worktrees_from_csv.py  # batchevaluate
│
├── TUDataset/                        # datasetdirectory
│   ├── defects4j-projects/           # 原始project仓库
│   │   ├── commons-csv/
│   │   ├── commons-cli/
│   │   ├── jackson-core/
│   │   └── ...
│   ├── worktrees/                    # Worktree output directory
│   ├── worktree_records.xlsx         # Worktree record表
│   ├── worktree_records.csv          # Worktree record表 (CSV)
│   ├── opencode_results/             # OpenCode executeresult
│   └── evaluation_results/           # evaluateresult
│
└── commit_summary.xlsx               # Commit 汇总表
```

### 必需file

- `commit_summary.xlsx`: 包含待process的 commit 列表（Project, CommitID, Type 列）
- project仓库：in `TUDataset/defects4j-projects/` 下

---

## 构建 Worktree

### 功能description

从 `commit_summary.xlsx` 读取 commit 列表，为每个 commit create独立的 worktree environment。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 为指定project构建 worktree
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core \
  --verbose
```

### parameterdescription

- `-i, --input`: input的 commit_summary.xlsx path
- `-o, --output`: output的record表path（支持 .xlsx 和 .csv）
- `--eval-dir`: Worktree output directory
- `--projects`: 要process的project列表（空格分隔）
- `--types`: 要process的class型列表（如 type1 type2���
- `--limit`: 最大process数量（用于测试）
- `--no-skip`: 不skip已存in的record
- `--verbose`: verbose logging output

### output

- **Worktree directory**: `{eval-dir}/{project}-task_{id}_eval/`
- **record表**: 同时generate `.xlsx` 和 `.csv` 两种format
- **状态**: successcreate的 worktree 状态为 `ready`

### 查看statistics

```bash
python batch_worktree_builder.py stats \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx
```

### clean up Worktree

```bash
# clean up指定project的所有 eval/* branch和 worktree
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core

# 预览将要delete的内容（不实际execute）
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli \
  --dry-run
```

---

## execute OpenCode

### 功能description

batch调用 OpenCode 对 worktree 中的obsolete test cases进行identify和update。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# batchexecute OpenCode
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2
```

### parameterdescription

- `-i, --input`: Worktree record表path
- `-o, --output`: OpenCode resultoutput directory
- `--projects`: 只process指定project
- `--types`: 只process指定class型（type1, type2 等）
- `--status`: 只process指定状态的 worktree（default ready）
- `--workers`: parallelexecute的task数（default 2）
- `--limit`: 最大process数量（用于测试）

### 测试run

```bash
# 先测试 5 个task
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2 \
  --limit 5
```

### output

- **taskresult**: `{output-dir}/{project}-task_{id}/`
  - `result.json`: executeresult
  - `prompt.txt`: 使用的 prompt
  - `modifications.json`: 修改内容
- **汇总file**: `{output-dir}/summary.json`

---

## 提取 GT data

### 功能description

从 worktree 中提取 Ground Truth（GT）测试变更data，用于后续evaluate。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 为指定project提取 GT data
python extract_gt_changes.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output identify_evaluation/gt_changes_all_updated.json \
  --project commons-cli jackson-core \
  --verbose
```

### parameterdescription

- `--input, -i`: Worktree record CSV file path
- `--output, -o`: output JSON file path
- `--project, -p`: 只process指定project（支持多个）
- `--task-range, -r`: task ID 范围（如 1-10）
- `--verbose, -v`: verbose logging output

### outputformat

```json
{
  "metadata": {
    "extraction_time": "2026-03-10T10:00:00",
    "total_tasks": 60,
    "successful": 60
  },
  "results": [
    {
      "task_id": 1,
      "project": "commons-cli",
      "v_0_commit": "00fb0a12",
      "test_changes": {
        "modified_files": [...],
        "added_files": [...],
        "deleted_files": [...]
      }
    }
  ]
}
```

---

## evaluateresult

### evaluate维度

TUBench 提供两种evaluate方式：

#### 1. identify准确度evaluate

evaluate用户（或工具）identifyobsolete test cases的准确度。

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output identify_evaluation/user_identification_results.json \
  --project commons-csv \
  --verbose
```

**evaluate指标**:
- Precision（precision）
- Recall（recall）
- F1 Score

#### 2. 完整evaluate（可execute性 + coverage + 改动量）

evaluate修复后的测试用例质量。

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# batchevaluate所有 ready 状态的 worktree
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --verbose
```

**evaluate指标**:
- **Executability Score（可execute性）**: compile和测试是否通过
- **Coverage Overlap Score（coverage重合度）**: 修改后的测试coverage与 GT 的重合度
- **Modification Score（改动量得分）**: 修改的代码量（越少越好）
- **Overall Score（综合得分）**: 上述三项的加权平均

### parameterdescription

- `--records, -r`: Worktree record CSV file path
- `--output-dir, -o`: evaluateresultoutput directory
- `--all-status`: evaluate所有状态（default只evaluate ready）
- `--limit`: 仅process前 N 条record（0 表示不限制）
- `--verbose, -v`: 详细log

### 测试run

```bash
# 先evaluate 5 个task
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --limit 5 \
  --verbose
```

### output file

- **单个taskresult**: `{project}-task_{id}_evaluation.json`
  - 包含详细的evaluateresult、errorinformation、coveragedata等
- **汇总 CSV**: `evaluation_summary.csv`
  - 包含所有task的得分汇总，便于分析
- **batchresult JSON**: `batch_evaluation_results.json`
  - 完整的batchevaluateresult

### 汇总 CSV format

```csv
task_id,project,executability_score,coverage_overlap_score,modification_score,overall_score,status,error,result_json
1,commons-cli,1.0,0.85,0.90,0.92,success,,/path/to/result.json
2,commons-cli,0.0,0.0,0.0,0.0,failed,Compilation failed,/path/to/result.json
```

---

## clean up资源

### clean up Worktree

```bash
# clean up指定project的 worktree 和branch
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core

# 预览模式（不实际delete）
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli \
  --dry-run
```

### clean upevaluateresult

```bash
# deleteevaluateresultdirectory
rm -rf /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results

# delete OpenCode result
rm -rf /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results
```

---

## 完整workflow程example

### scenario：为 commons-cli 和 jackson-core project构建、execute、evaluate

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 步骤 1: 构建 Worktree
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core \
  --verbose

# 步骤 2: execute OpenCode（先测试 5 个）
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2 \
  --limit 5

# 步骤 3: 提取 GT data
python extract_gt_changes.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output identify_evaluation/gt_changes_new_projects.json \
  --project commons-cli jackson-core \
  --verbose

# 步骤 4: evaluateresult（先测试 5 个）
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --limit 5 \
  --verbose

# 步骤 5: 查看result
cat /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results/evaluation_summary.csv

# 步骤 6: 如果测试通过，execute完整evaluate
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --verbose
```

---

## 常见问题

### Q1: 找不到 GT data

**问题**: executeevaluate时提示 "未foundGTdata"

**原因**: GT datafile中不包含该project的data

**解决**: 使用 `extract_gt_changes.py` 为新projectgenerate GT data

### Q2: Worktree 已存in

**问题**: 构建 worktree 时提示已存in

**解决**:
- 使用 `--no-skip` parameter强制重建
- 或先使用 `clean` 命令clean up

### Q3: evaluatefail

**问题**: evaluate时compile或测试fail

**排查**:
1. check worktree path是否正确
2. checkproject是否能正常compile
3. 查看详细���errorlog（使用 `--verbose`）
4. checkevaluateresult JSON 中的 `error` 字段

### Q4: parallelexecute出错

**问题**: OpenCode parallelexecute时出现error

**解决**: 降低 `--workers` parameter值，或设置为 1 串行execute

---

## script修改record

### batch_worktree_builder.py

- **修改**: 支持 CSV 和 XLSX 双format读写
- **功能**: save时自动generate两种formatfile

### extract_gt_changes.py

- **修改**: `--project` parameter支持多projects
- **功能**: 可以一次性为多projects提取 GT data

---

## 相关文档

- [BATCH_OPENCODE_GUIDE.md](../baseline/opencode/docs/BATCH_OPENCODE_GUIDE.md): OpenCode batchexecute详细指南
- [EVALUATION_FIX_SUMMARY.md](../baseline/opencode/docs/EVALUATION_FIX_SUMMARY.md): evaluate系统修复总结
- [PROPOSALS.md](PROPOSALS.md): projectproposal和设计文档

---

## 联系方式

如有问题，请查看project README 或commit Issue。

**最后update**: 2026-03-10
