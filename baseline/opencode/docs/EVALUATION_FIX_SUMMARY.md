# 评估脚本修复总结

## 🔧 已修复的问题

### 问题1: Maven RAT License检查失败

**症状**:
```
[ERROR] Failed to execute goal org.apache.rat:apache-rat-plugin:0.13:check
(rat-check) on project commons-csv: Too many files with unapproved license
```

**原因**:
OpenCode生成的临时文件（如`javac.20260303_201755.args`）没有Apache license header，导致RAT插件检查失败。

**修复**:
在所有Maven命令中添加了跳过RAT检查的参数：
- `executability_evaluator.py`: 第111行和第164行
- `coverage_increment_analyzer.py`: 第227行

修改后的命令包含：
```bash
-Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true
```

## ✅ 修复后的文件

1. **evaluation/executability_evaluator.py**
   - 编译命令（第111行）：已包含跳过参数
   - 测试命令（第164行）：✅ 已添加跳过参数

2. **evaluation/coverage_increment_analyzer.py**
   - 测试命令（第227行）：✅ 已添加跳过参数

## 🚀 如何使用评估脚本

### 当前状态
评估脚本正在运行中，处理5个测试任务。预计需要5-10分钟完成。

### 等待评估完成

```bash
# 检查评估是否完成
ls -lh /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json

# 或者监控进程
ps aux | grep evaluate_opencode_results
```

### 评估完成后查看结果

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate

# 查看汇总
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)
    meta = data['metadata']
    scores = meta.get('average_scores', {})

    print('=== 评估汇总 ===')
    print(f'总任务数: {meta[\"total_tasks\"]}')
    print(f'成功: {meta[\"successful\"]}')
    print(f'失败: {meta[\"failed\"]}')
    print()
    print('=== 平均得分 ===')
    print(f'覆盖重合度: {scores.get(\"avg_coverage_overlap\", 0):.2%}')
    print(f'改动量得分: {scores.get(\"avg_modification_score\", 0):.2%}')
    print(f'综合得分: {scores.get(\"avg_overall_score\", 0):.2%}')
    print()
    print('=== 成功率 ===')
    print(f'编译成功率: {scores.get(\"compile_success_rate\", 0):.2%}')
    print(f'测试成功率: {scores.get(\"test_success_rate\", 0):.2%}')
"
```

## 📊 评估指标说明

### 1. 覆盖重合度 (Coverage Overlap)
- **含义**: User修改与GT修改在覆盖增量上的重合程度
- **计算**: `|User增量 ∩ GT增量| / |GT增量|`
- **范围**: 0-100%，越高越好

### 2. 改动量得分 (Modification Score)
- **含义**: 基于Jaccard相似度，衡量修改的精简程度
- **计算**: `Jaccard = |User ∩ GT| / |User ∪ GT|`
- **范围**: 0-100%，越高表示改动越少（越接近GT）

### 3. 综合得分 (Overall Score)
- **公式**: `0.6 × 覆盖重合度 + 0.4 × 改动量得分`
- **范围**: 0-100%，越高越好

### 4. 编译成功率
- **含义**: 修改后的测试代码能否编译通过
- **范围**: 0-100%

### 5. 测试成功率
- **含义**: 修改后的测试能否执行通过
- **范围**: 0-100%

## 🔄 完整工作流

### 步骤1: 执行OpenCode（已完成✅）
```bash
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/Tet/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --limit 5 \
  --verbose
```

**结果**: 5个任务全部成功，平均耗时452.8秒/任务

### 步骤2: 评估结果（进行���⏳）
```bash
python evaluate_opencode_results.py \
  --opencode-results /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --worktree-records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --project-base /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  --output /Users/mac/Desktop/TestUTUDataset/evaluation_results_test.json \
  --verbose
```

**状态**: 正在运行，预计5-10分钟完成

### 步骤3: 分析结果（待完成）
评估完成后，可以：
- 查看汇总统计
- 生成CSV报告
- 按项目/类型分析
- 对比不同baseline

## 📝 下一步

### 如果测试评估成功

1. **执行全部60个任务**
```bash
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --verbose
```

预计时间: 60 × 7.5分钟 / 2 workers = 约3.75小时

2. **评估全部结果**
```bash
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \
  --verbose
```

## 🐛 故障排查

### 如果评估失败

1. **检查日志**
```bash
# 查看详细日志（如果使用了--verbose）
# 日志会显示在终端输出中
```

2. **检查worktree状态**
```bash
cd /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval
git status
mvn clean compile -Drat.skip=true
```

3. **手动测试单个任务**
```bash
# 使用evaluate.py手动评估单个worktree
python evaluate.py run \
  --worktree /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval \
  --gt-commit 030fb8e3 \
  --output test_result.json
```

## 📚 相关文档

- `docs/EVALUATE_OPENCODE_RESULTS.md` - 详细评估指南
- `docs/BATCH_OPENCODE_GUIDE.md` - OpenCode批量执行指南
- `docs/RUN_OPENCODE_COMMONS_CSV_GSON.md` - 在commons-csv和gson上执行指南

## ✨ 总结

**已完成**:
- ✅ 修复Maven RAT检查问题
- ✅ OpenCode成功执行5个任务
- ✅ 评估脚本正在运行

**进行中**:
- ⏳ 评估5个测试任务（预计5-10分钟）

**待完成**:
- ⏸️ 查看评估结果
- ⏸️ 执行全部60个任务
- ⏸️ 生成最终报告
