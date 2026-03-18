# 评估OpenCode执行结果 - 完整指南

## 📊 评估指标说明

### 1. 可执行性 (Executability)
- **编译成功率**: 修改后的测试代码能否编译通过
- **测试成功率**: 修改后的测试能否执行通过
- **测试统计**: 通过/失败/错误的测试数量

### 2. 覆盖增量重合度 (Coverage Overlap)
- **行覆盖重合度**: User修改与GT修改在覆盖增量上的重合程度
- **分支覆盖重合度**: 分支覆盖的重合程度
- **计算公式**: `重合度 = |User增量 ∩ GT增量| / |GT增量|`

### 3. 改动量 (Modification Effort)
- **修改的测试方法数**: 有多少测试方法被修改
- **改动量得分**: 基于Jaccard相似度，越高表示改动越少（越接近GT）
- **计算公式**: `Jaccard = |User ∩ GT| / |User ∪ GT|`

### 4. 综合得分 (Overall Score)
- **公式**: `0.6 × 覆盖重合度 + 0.4 × 改动量得分`
- **范围**: 0-100%，越高越好

### 5. 时间效率
- **OpenCode执行时间**: 每个任务的耗时
- **平均执行时间**: 所有任务的平均耗时

## 🚀 快速开始

### 步骤1: 确认OpenCode执行完成

检查OpenCode执行结果：

```bash
# 查看汇总
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json

# 确认所有任务成功
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json') as f:
    s = json.load(f)
    print(f'Total: {s[\"total\"]}')
    print(f'Successful: {s[\"successful\"]}')
    print(f'Failed: {s[\"failed\"]}')
"
```

### 步骤2: 执行评估

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate

python evaluate_opencode_results.py \
  --opencode-results /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --worktree-records /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --project-base /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  --output /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json \
  --verbose
```

### 步骤3: 查看评估结果

```bash
# 查看汇总信息
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)
    meta = data['metadata']
    scores = meta['average_scores']

    print('=== 评估汇总 ===')
    print(f'总任务数: {meta[\"total_tasks\"]}')
    print(f'成功: {meta[\"successful\"]}')
    print(f'失败: {meta[\"failed\"]}')
    print()
    print('=== 平均得分 ===')
    print(f'覆盖重合度: {scores[\"avg_coverage_overlap\"]:.2%}')
    print(f'改动量得分: {scores[\"avg_modification_score\"]:.2%}')
    print(f'综合得分: {scores[\"avg_overall_score\"]:.2%}')
    print()
    print('=== 成功率 ===')
    print(f'编译成功率: {scores[\"compile_success_rate\"]:.2%}')
    print(f'测试成功率: {scores[\"test_success_rate\"]:.2%}')
"
```

## 📋 完整工作流

### 1. 执行OpenCode（已完成）

```bash
# 测试5个任务
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --limit 5 \
  --verbose
```

### 2. 评估结果

```bash
# 评估测试结果
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json \
  --verbose
```

### 3. 如果测试成功，执行全部60个任务

```bash
# 执行全部任务
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --verbose

# 评估全部结果
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \
  --verbose
```

## 📊 结果分析

### 评估结果文件结构

```json
{
  "metadata": {
    "evaluation_time": "2026-03-03T20:00:00",
    "total_tasks": 5,
    "successful": 5,
    "failed": 0,
    "average_scores": {
      "avg_coverage_overlap": 0.85,
      "avg_modification_score": 0.75,
      "avg_overall_score": 0.81,
      "compile_success_rate": 1.0,
      "test_success_rate": 0.8
    }
  },
  "results": [
    {
      "task_id": 1,
      "project": "commons-csv",
      "gt_commit": "030fb8e3",
      "worktree_path": "/path/to/worktree",
      "opencode_execution": {
        "duration": 685.1,
        "modified_files": ["src/test/java/..."]
      },
      "evaluation": {
        "executability": {
          "compile_success": true,
          "test_success": true,
          "test_results": {
            "passed": 150,
            "failed": 2,
            "errors": 0
          }
        },
        "coverage_overlap": {
          "line_overlap_ratio": 0.85,
          "branch_overlap_ratio": 0.80,
          "gt_increment_lines": 100,
          "user_increment_lines": 95
        },
        "modification_effort": {
          "total_methods": 5,
          "average_score": 0.75
        }
      },
      "scores": {
        "coverage_overlap": 0.85,
        "modification_score": 0.75,
        "overall": 0.81
      },
      "success": true
    }
  ]
}
```

### 生成详细报告

```bash
# 生成CSV格式报告
python3 -c "
import json
import csv

with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)

with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_report.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow([
        'Task ID', 'Project', 'GT Commit',
        'Compile Success', 'Test Success',
        'Coverage Overlap', 'Modification Score', 'Overall Score',
        'OpenCode Duration (s)', 'Modified Files Count'
    ])

    for r in data['results']:
        if r.get('success'):
            exec_result = r['evaluation']['executability']
            scores = r['scores']
            opencode = r['opencode_execution']

            writer.writerow([
                r['task_id'],
                r['project'],
                r['gt_commit'],
                'Yes' if exec_result.get('compile_success') else 'No',
                'Yes' if exec_result.get('test_success') else 'No',
                f\"{scores.get('coverage_overlap', 0):.2%}\",
                f\"{scores.get('modification_score', 0):.2%}\",
                f\"{scores.get('overall', 0):.2%}\",
                f\"{opencode.get('duration', 0):.1f}\",
                len(opencode.get('modified_files', []))
            ])

print('Report saved to: evaluation_report.csv')
"
```

### 按项目统计

```bash
python3 -c "
import json
from collections import defaultdict

with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)

by_project = defaultdict(list)
for r in data['results']:
    if r.get('success'):
        by_project[r['project']].append(r)

print('=== 按项目统计 ===')
for project, results in by_project.items():
    avg_overall = sum(r['scores']['overall'] for r in results) / len(results)
    avg_duration = sum(r['opencode_execution']['duration'] for r in results) / len(results)

    print(f'\n{project}:')
    print(f'  任务数: {len(results)}')
    print(f'  平均综合得分: {avg_overall:.2%}')
    print(f'  平均执行时间: {avg_duration:.1f}秒')
"
```

### 按类型统计

```bash
python3 -c "
import json
import pandas as pd

# 读取评估结果
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    eval_data = json.load(f)

# 读取worktree记录获取类型信息
df = pd.read_excel('/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx')

print('=== 按类型统计 ===')
for commit_type in ['type1', 'type2']:
    type_tasks = df[df['type'] == commit_type]['task_id'].tolist()
    type_results = [r for r in eval_data['results']
                   if r.get('success') and r['task_id'] in type_tasks]

    if type_results:
        avg_overall = sum(r['scores']['overall'] for r in type_results) / len(type_results)
        compile_rate = sum(1 for r in type_results
                          if r['evaluation']['executability']['compile_success']) / len(type_results)

        print(f'\n{commit_type}:')
        print(f'  任务数: {len(type_results)}')
        print(f'  平均综合得分: {avg_overall:.2%}')
        print(f'  编译成功率: {compile_rate:.2%}')
"
```

## 🔍 深入分析

### 查看单个任务的详细结果

```bash
python3 -c "
import json

with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)

# 查看第一个任务
result = data['results'][0]

print('=== Task', result['task_id'], '===')
print(f'Project: {result[\"project\"]}')
print(f'GT Commit: {result[\"gt_commit\"]}')
print()

exec_result = result['evaluation']['executability']
print('[可执行性]')
print(f'  编译: {\"✓\" if exec_result[\"compile_success\"] else \"✗\"}')
print(f'  测试: {\"✓\" if exec_result[\"test_success\"] else \"✗\"}')
if exec_result.get('test_results'):
    tr = exec_result['test_results']
    print(f'  测试统计: {tr.get(\"passed\", 0)} 通过, {tr.get(\"failed\", 0)} 失败')
print()

cov_result = result['evaluation']['coverage_overlap']
print('[覆盖重合度]')
print(f'  行覆盖: {cov_result[\"line_overlap_ratio\"]:.2%}')
print(f'  分支覆盖: {cov_result[\"branch_overlap_ratio\"]:.2%}')
print()

effort_result = result['evaluation']['modification_effort']
print('[改动量]')
print(f'  修改方法数: {effort_result[\"total_methods\"]}')
print(f'  改动量得分: {effort_result[\"average_score\"]:.2%}')
print()

print('[综合得分]')
print(f'  最终得分: {result[\"scores\"][\"overall\"]:.2%}')
print()

print('[OpenCode执行]')
print(f'  耗时: {result[\"opencode_execution\"][\"duration\"]:.1f}秒')
print(f'  修改文件数: {len(result[\"opencode_execution\"][\"modified_files\"])}')
"
```

### 对比不同方法

如果你有多个baseline的结果，可以对比：

```bash
python3 -c "
import json

# 读取OpenCode结果
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    opencode_data = json.load(f)

# 如果有其他baseline的结果，也可以读取
# with open('other_baseline_results.json') as f:
#     other_data = json.load(f)

print('=== Baseline对比 ===')
print(f'OpenCode:')
scores = opencode_data['metadata']['average_scores']
print(f'  综合得分: {scores[\"avg_overall_score\"]:.2%}')
print(f'  覆盖重合度: {scores[\"avg_coverage_overlap\"]:.2%}')
print(f'  改动量得分: {scores[\"avg_modification_score\"]:.2%}')
print(f'  编译成功率: {scores[\"compile_success_rate\"]:.2%}')
print(f'  测试成功率: {scores[\"test_success_rate\"]:.2%}')
"
```

## ⏱️ 时间效率分析

### 分析OpenCode执行时间

```bash
python3 -c "
import json

with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json') as f:
    summary = json.load(f)

print('=== OpenCode执行时间分析 ===')
print(f'总耗时: {summary[\"total_duration\"]:.1f}秒 ({summary[\"total_duration\"]/60:.1f}分钟)')
print(f'平均耗时: {summary[\"avg_duration\"]:.1f}秒/任务')
print()

# 按任务分析
durations = [r['duration'] for r in summary['results'] if r.get('success')]
durations.sort()

print('耗时分布:')
print(f'  最快: {min(durations):.1f}秒')
print(f'  最慢: {max(durations):.1f}秒')
print(f'  中位数: {durations[len(durations)//2]:.1f}秒')
"
```

## 📝 注意事项

1. **评估前确认**: 确保OpenCode执行完成且所有任务成功
2. **项目路径**: 确保`--project-base`指向正确的项目目录
3. **GT commit**: 从worktree_records.xlsx自动获取
4. **评估时间**: 评估过程需要编译和运行测试，可能需要较长时间
5. **并行评估**: 目前是串行评估，如需加速可以修改代码支持并行

## 🎯 下一步

评估完成后，你可以：

1. **分析结果**: 查看哪些任务得分高，哪些得分低
2. **对比baseline**: 与其他方法对比
3. **改进prompt**: 根据结果调整prompt策略
4. **扩展数据集**: 在更多项目上测试
5. **发表论文**: 使用评估结果撰写论文

## 📞 需要帮助？

如果遇到问题：
1. 查看详细日志: 使用`--verbose`参数
2. 检查worktree状态: 确认修改已保存
3. 验证GT commit: 确认commit hash正确
4. 测试单个任务: 先评估一个任务验证流程
