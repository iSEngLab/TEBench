# TUBench 完整工作流程指南

本文档总结了 TUBench 从构建 worktree 到评估结果的完整流程。

## 目录

1. [环境准备](#环境准备)
2. [构建 Worktree](#构建-worktree)
3. [执行 OpenCode](#执行-opencode)
4. [提取 GT 数据](#提取-gt-数据)
5. [评估结果](#评估结果)
6. [清理资源](#清理资源)

---

## 环境准备

### 目录结构

```
/Users/mac/Desktop/TestUpdate/
├── TUBench/                          # 主项目目录
│   ├── batch_worktree_builder.py     # Worktree 批量构建工具
│   ├── extract_gt_changes.py         # GT 数据提取工具
│   ├── evaluate_user_identification.py  # 识别准确度评估
│   └── baseline/opencode/scripts/
│       ├── batch_opencode_runner.py  # OpenCode 批量执行
│       └── batch_evaluate_worktrees_from_csv.py  # 批量评估
│
├── TUDataset/                        # 数据集目录
│   ├── defects4j-projects/           # 原始项目仓库
│   │   ├── commons-csv/
│   │   ├── commons-cli/
│   │   ├── jackson-core/
│   │   └── ...
│   ├── worktrees/                    # Worktree 输出目录
│   ├── worktree_records.xlsx         # Worktree 记录表
│   ├── worktree_records.csv          # Worktree 记录表 (CSV)
│   ├── opencode_results/             # OpenCode 执行结果
│   └── evaluation_results/           # 评估结果
│
└── commit_summary.xlsx               # Commit 汇总表
```

### 必需文件

- `commit_summary.xlsx`: 包含待处理的 commit 列表（Project, CommitID, Type 列）
- 项目仓库：在 `TUDataset/defects4j-projects/` 下

---

## 构建 Worktree

### 功能说明

从 `commit_summary.xlsx` 读取 commit 列表，为每个 commit 创建独立的 worktree 环境。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 为指定项目构建 worktree
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core \
  --verbose
```

### 参数说明

- `-i, --input`: 输入的 commit_summary.xlsx 路径
- `-o, --output`: 输出的记录表路径（支持 .xlsx 和 .csv）
- `--eval-dir`: Worktree 输出目录
- `--projects`: 要处理的项目列表（空格分隔）
- `--types`: 要处理的类型列表（如 type1 type2���
- `--limit`: 最大处理数量（用于测试）
- `--no-skip`: 不跳过已存在的记录
- `--verbose`: 详细日志输出

### 输出

- **Worktree 目录**: `{eval-dir}/{project}-task_{id}_eval/`
- **记录表**: 同时生成 `.xlsx` 和 `.csv` 两种格式
- **状态**: 成功创建的 worktree 状态为 `ready`

### 查看统计信息

```bash
python batch_worktree_builder.py stats \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx
```

### 清理 Worktree

```bash
# 清理指定项目的所有 eval/* 分支和 worktree
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core

# 预览将要删除的内容（不实际执行）
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli \
  --dry-run
```

---

## 执行 OpenCode

### 功能说明

批量调用 OpenCode 对 worktree 中的过时测试用例进行识别和更新。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 批量执行 OpenCode
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2
```

### 参数说明

- `-i, --input`: Worktree 记录表路径
- `-o, --output`: OpenCode 结果输出目录
- `--projects`: 只处理指定项目
- `--types`: 只处理指定类型（type1, type2 等）
- `--status`: 只处理指定状态的 worktree（默认 ready）
- `--workers`: 并行执行的任务数（默认 2）
- `--limit`: 最大处理数量（用于测试）

### 测试运行

```bash
# 先测试 5 个任务
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2 \
  --limit 5
```

### 输出

- **任务结果**: `{output-dir}/{project}-task_{id}/`
  - `result.json`: 执行结果
  - `prompt.txt`: 使用的 prompt
  - `modifications.json`: 修改内容
- **汇总文件**: `{output-dir}/summary.json`

---

## 提取 GT 数据

### 功能说明

从 worktree 中提取 Ground Truth（GT）测试变更数据，用于后续评估。

### 命令

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 为指定项目提取 GT 数据
python extract_gt_changes.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output identify_evaluation/gt_changes_all_updated.json \
  --project commons-cli jackson-core \
  --verbose
```

### 参数说明

- `--input, -i`: Worktree 记录 CSV 文件路径
- `--output, -o`: 输出 JSON 文件路径
- `--project, -p`: 只处理指定项目（支持多个）
- `--task-range, -r`: 任务 ID 范围（如 1-10）
- `--verbose, -v`: 详细日志输出

### 输出格式

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

## 评估结果

### 评估维度

TUBench 提供两种评估方式：

#### 1. 识别准确度评估

评估用户（或工具）识别过时测试用例的准确度。

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output identify_evaluation/user_identification_results.json \
  --project commons-csv \
  --verbose
```

**评估指标**:
- Precision（精确率）
- Recall（召回率）
- F1 Score

#### 2. 完整评估（可执行性 + 覆盖率 + 改动量）

评估修复后的测试用例质量。

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 批量评估所有 ready 状态的 worktree
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --verbose
```

**评估指标**:
- **Executability Score（可执行性）**: 编译和测试是否通过
- **Coverage Overlap Score（覆盖率重合度）**: 修改后的测试覆盖率与 GT 的重合度
- **Modification Score（改动量得分）**: 修改的代码量（越少越好）
- **Overall Score（综合得分）**: 上述三项的加权平均

### 参数说明

- `--records, -r`: Worktree 记录 CSV 文件路径
- `--output-dir, -o`: 评估结果输出目录
- `--all-status`: 评估所有状态（默认只评估 ready）
- `--limit`: 仅处理前 N 条记录（0 表示不限制）
- `--verbose, -v`: 详细日志

### 测试运行

```bash
# 先评估 5 个任务
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --limit 5 \
  --verbose
```

### 输出文件

- **单个任务结果**: `{project}-task_{id}_evaluation.json`
  - 包含详细的评估结果、错误信息、覆盖率数据等
- **汇总 CSV**: `evaluation_summary.csv`
  - 包含所有任务的得分汇总，便于分析
- **批量结果 JSON**: `batch_evaluation_results.json`
  - 完整的批量评估结果

### 汇总 CSV 格式

```csv
task_id,project,executability_score,coverage_overlap_score,modification_score,overall_score,status,error,result_json
1,commons-cli,1.0,0.85,0.90,0.92,success,,/path/to/result.json
2,commons-cli,0.0,0.0,0.0,0.0,failed,Compilation failed,/path/to/result.json
```

---

## 清理资源

### 清理 Worktree

```bash
# 清理指定项目的 worktree 和分支
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core

# 预览模式（不实际删除）
python batch_worktree_builder.py clean \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli \
  --dry-run
```

### 清理评估结果

```bash
# 删除评估结果目录
rm -rf /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results

# 删除 OpenCode 结果
rm -rf /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results
```

---

## 完整工作流程示例

### 场景：为 commons-cli 和 jackson-core 项目构建、执行、评估

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 步骤 1: 构建 Worktree
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-cli jackson-core \
  --verbose

# 步骤 2: 执行 OpenCode（先测试 5 个）
python baseline/opencode/scripts/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --projects commons-cli jackson-core \
  --status ready \
  --workers 2 \
  --limit 5

# 步骤 3: 提取 GT 数据
python extract_gt_changes.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output identify_evaluation/gt_changes_new_projects.json \
  --project commons-cli jackson-core \
  --verbose

# 步骤 4: 评估结果（先测试 5 个）
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --limit 5 \
  --verbose

# 步骤 5: 查看结果
cat /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results/evaluation_summary.csv

# 步骤 6: 如果测试通过，执行完整评估
python baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py \
  --records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --output-dir /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results \
  --verbose
```

---

## 常见问题

### Q1: 找不到 GT 数据

**问题**: 执行评估时提示 "未找到GT数据"

**原因**: GT 数据文件中不包含该项目的数据

**解决**: 使用 `extract_gt_changes.py` 为新项目生成 GT 数据

### Q2: Worktree 已存在

**问题**: 构建 worktree 时提示已存在

**解决**:
- 使用 `--no-skip` 参数强制重建
- 或先使用 `clean` 命令清理

### Q3: 评估失败

**问题**: 评估时编译或测试失败

**排查**:
1. 检查 worktree 路径是否正确
2. 检查项目是否能正常编译
3. 查看详细���错误日志（使用 `--verbose`）
4. 检查评估结果 JSON 中的 `error` 字段

### Q4: 并行执行出错

**问题**: OpenCode 并行执行时出现错误

**解决**: 降低 `--workers` 参数值，或设置为 1 串行执行

---

## 脚本修改记录

### batch_worktree_builder.py

- **修改**: 支持 CSV 和 XLSX 双格式读写
- **功能**: 保存时自动生成两种格式文件

### extract_gt_changes.py

- **修改**: `--project` 参数支持多个项目
- **功能**: 可以一次性为多个项目提取 GT 数据

---

## 相关文档

- [BATCH_OPENCODE_GUIDE.md](../baseline/opencode/docs/BATCH_OPENCODE_GUIDE.md): OpenCode 批量执行详细指南
- [EVALUATION_FIX_SUMMARY.md](../baseline/opencode/docs/EVALUATION_FIX_SUMMARY.md): 评估系统修复总结
- [PROPOSALS.md](PROPOSALS.md): 项目提案和设计文档

---

## 联系方式

如有问题，请查看项目 README 或提交 Issue。

**最后更新**: 2026-03-10
