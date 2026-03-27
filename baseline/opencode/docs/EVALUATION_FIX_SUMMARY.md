# evaluatescript修复总结

## 🔧 已修复的问题

### 问题1: Maven RAT Licensecheckfail

**症状**:
```
[ERROR] Failed to execute goal org.apache.rat:apache-rat-plugin:0.13:check
(rat-check) on project commons-csv: Too many files with unapproved license
```

**原因**:
OpenCodegenerate的临时file（如`javac.20260303_201755.args`）没有Apache license header，导致RAT插件checkfail。

**修复**:
in所有Maven command中添加了skipRATcheck的parameter：
- `executability_evaluator.py`: 第111行和第164行
- `coverage_increment_analyzer.py`: 第227行

修改后的命令包含：
```bash
-Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true
```

## ✅ 修复后的file

1. **evaluation/executability_evaluator.py**
   - compile命令（第111行）：已包含skipparameter
   - 测试命令（第164行）：✅ 已添加skipparameter

2. **evaluation/coverage_increment_analyzer.py**
   - 测试命令（第227行）：✅ 已添加skipparameter

## 🚀 如何使用evaluatescript

### 当前状态
evaluatescript正inrun中，process5个测试task。预计需要5-10分钟complete。

### waitingevaluatecomplete

```bash
# checkevaluate是否complete
ls -lh /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json

# 或者监控process
ps aux | grep evaluate_opencode_results
```

### evaluatecomplete后查看result

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

    print('=== evaluate汇总 ===')
    print(f'总task数: {meta[\"total_tasks\"]}')
    print(f'Succeeded: {meta[\"successful\"]}')
    print(f'Failed: {meta[\"failed\"]}')
    print()
    print('=== 平均得分 ===')
    print(f'覆盖重合度: {scores.get(\"avg_coverage_overlap\", 0):.2%}')
    print(f'改动量得分: {scores.get(\"avg_modification_score\", 0):.2%}')
    print(f'综合得分: {scores.get(\"avg_overall_score\", 0):.2%}')
    print()
    print('=== success率 ===')
    print(f'compilesuccess率: {scores.get(\"compile_success_rate\", 0):.2%}')
    print(f'测试success率: {scores.get(\"test_success_rate\", 0):.2%}')
"
```

## 📊 evaluate指标description

### 1. 覆盖重合度 (Coverage Overlap)
- **含义**: User修改与GT修改in覆盖增量上的重合程度
- **calculate**: `|User增量 ∩ GT增量| / |GT增量|`
- **范围**: 0-100%，越高越好

### 2. 改动量得分 (Modification Score)
- **含义**: 基于Jaccard相似度，衡量修改的精简程度
- **calculate**: `Jaccard = |User ∩ GT| / |User ∪ GT|`
- **范围**: 0-100%，越高表示改动越少（越接近GT）

### 3. 综合得分 (Overall Score)
- **公式**: `0.6 × 覆盖重合度 + 0.4 × 改动量得分`
- **范围**: 0-100%，越高越好

### 4. compilesuccess率
- **含义**: 修改后的test code能否compile通过
- **范围**: 0-100%

### 5. 测试success率
- **含义**: 修改后的测试能否execute通过
- **范围**: 0-100%

## 🔄 完整workflow

### 步骤1: executeOpenCode（已complete✅）
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

**result**: 5个task全部success，平均耗时452.8秒/task

### 步骤2: evaluateresult（进行���⏳）
```bash
python evaluate_opencode_results.py \
  --opencode-results /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --worktree-records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --project-base /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  --output /Users/mac/Desktop/TestUTUDataset/evaluation_results_test.json \
  --verbose
```

**状态**: 正inrun，预计5-10分钟complete

### 步骤3: 分析result（待complete）
evaluatecomplete后，可以：
- 查看汇总statistics
- generateCSVreport
- 按project/class型分析
- 对比不同baseline

## 📝 下一步

### 如果测试evaluatesuccess

1. **execute全部60个task**
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

2. **evaluate全部result**
```bash
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \
  --verbose
```

## 🐛 故障排查

### 如果evaluatefail

1. **checklog**
```bash
# 查看详细log（如果使用了--verbose）
# log会显示in终端output中
```

2. **checkworktree状态**
```bash
cd /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval
git status
mvn clean compile -Drat.skip=true
```

3. **手动测试单个task**
```bash
# 使用evaluate.py手动evaluate单个worktree
python evaluate.py run \
  --worktree /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval \
  --gt-commit 030fb8e3 \
  --output test_result.json
```

## 📚 相关文档

- `docs/EVALUATE_OPENCODE_RESULTS.md` - 详细evaluate指南
- `docs/BATCH_OPENCODE_GUIDE.md` - OpenCodebatchexecute指南
- `docs/RUN_OPENCODE_COMMONS_CSV_GSON.md` - incommons-csv和gson上execute指南

## ✨ 总结

**已complete**:
- ✅ 修复Maven RATcheck问题
- ✅ OpenCodesuccessexecute5个task
- ✅ evaluatescript正inrun

**进行中**:
- ⏳ evaluate5个测试task（预计5-10分钟）

**待complete**:
- ⏸️ 查看evaluateresult
- ⏸️ execute全部60个task
- ⏸️ generate最终report
