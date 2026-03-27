# evaluateOpenCodeexecuteresult - 完整指南

## 📊 evaluate指标description

### 1. 可execute性 (Executability)
- **compilesuccess率**: 修改后的test code能否compile通过
- **测试success率**: 修改后的测试能否execute通过
- **测试statistics**: 通过/fail/error的测试数量

### 2. 覆盖增量重合度 (Coverage Overlap)
- **行覆盖重合度**: User修改与GT修改in覆盖增量上的重合程度
- **branch覆盖重合度**: branch覆盖的重合程度
- **calculate公式**: `重合度 = |User增量 ∩ GT增量| / |GT增量|`

### 3. 改动量 (Modification Effort)
- **修改的测试method数**: 有多少测试method被修改
- **改动量得分**: 基于Jaccard相似度，越高表示改动越少（越接近GT）
- **calculate公式**: `Jaccard = |User ∩ GT| / |User ∪ GT|`

### 4. 综合得分 (Overall Score)
- **公式**: `0.6 × 覆盖重合度 + 0.4 × 改动量得分`
- **范围**: 0-100%，越高越好

### 5. 时间效率
- **OpenCodeexecute时间**: 每个task的耗时
- **平均execute时间**: 所有task的平均耗时

## 🚀 快速start

### 步骤1: 确认OpenCodeexecutecomplete

checkOpenCodeexecuteresult：

```bash
# 查看汇总
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json

# 确认所有tasksuccess
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json') as f:
    s = json.load(f)
    print(f'Total: {s[\"total\"]}')
    print(f'Successful: {s[\"successful\"]}')
    print(f'Failed: {s[\"failed\"]}')
"
```

### 步骤2: executeevaluate

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

### 步骤3: 查看evaluateresult

```bash
# 查看汇总information
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)
    meta = data['metadata']
    scores = meta['average_scores']

    print('=== evaluate汇总 ===')
    print(f'总task数: {meta[\"total_tasks\"]}')
    print(f'Succeeded: {meta[\"successful\"]}')
    print(f'Failed: {meta[\"failed\"]}')
    print()
    print('=== 平均得分 ===')
    print(f'覆盖重合度: {scores[\"avg_coverage_overlap\"]:.2%}')
    print(f'改动量得分: {scores[\"avg_modification_score\"]:.2%}')
    print(f'综合得分: {scores[\"avg_overall_score\"]:.2%}')
    print()
    print('=== success率 ===')
    print(f'compilesuccess率: {scores[\"compile_success_rate\"]:.2%}')
    print(f'测试success率: {scores[\"test_success_rate\"]:.2%}')
"
```

## 📋 完整workflow

### 1. executeOpenCode（已complete）

```bash
# 测试5个task
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

### 2. evaluateresult

```bash
# evaluate测试result
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json \
  --verbose
```

### 3. 如果测试success，execute全部60个task

```bash
# execute全部task
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --verbose

# evaluate全部result
python evaluate_opencode_results.py \
  -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \
  --verbose
```

## 📊 result分析

### evaluateresultfile结构

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

### generate详细report

```bash
# generateCSVformatreport
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

### 按projectstatistics

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

print('=== 按projectstatistics ===')
for project, results in by_project.items():
    avg_overall = sum(r['scores']['overall'] for r in results) / len(results)
    avg_duration = sum(r['opencode_execution']['duration'] for r in results) / len(results)

    print(f'\n{project}:')
    print(f'  task数: {len(results)}')
    print(f'  平均综合得分: {avg_overall:.2%}')
    print(f'  平均execute时间: {avg_duration:.1f}秒')
"
```

### 按class型statistics

```bash
python3 -c "
import json
import pandas as pd

# 读取evaluateresult
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    eval_data = json.load(f)

# 读取worktreerecordgetclass型information
df = pd.read_excel('/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx')

print('=== 按class型statistics ===')
for commit_type in ['type1', 'type2']:
    type_tasks = df[df['type'] == commit_type]['task_id'].tolist()
    type_results = [r for r in eval_data['results']
                   if r.get('success') and r['task_id'] in type_tasks]

    if type_results:
        avg_overall = sum(r['scores']['overall'] for r in type_results) / len(type_results)
        compile_rate = sum(1 for r in type_results
                          if r['evaluation']['executability']['compile_success']) / len(type_results)

        print(f'\n{commit_type}:')
        print(f'  task数: {len(type_results)}')
        print(f'  平均综合得分: {avg_overall:.2%}')
        print(f'  compilesuccess率: {compile_rate:.2%}')
"
```

## 🔍 深入分析

### 查看单个task的详细result

```bash
python3 -c "
import json

with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    data = json.load(f)

# 查看第一个task
result = data['results'][0]

print('=== Task', result['task_id'], '===')
print(f'Project: {result[\"project\"]}')
print(f'GT Commit: {result[\"gt_commit\"]}')
print()

exec_result = result['evaluation']['executability']
print('[可execute性]')
print(f'  compile: {\"✓\" if exec_result[\"compile_success\"] else \"✗\"}')
print(f'  测试: {\"✓\" if exec_result[\"test_success\"] else \"✗\"}')
if exec_result.get('test_results'):
    tr = exec_result['test_results']
    print(f'  测试statistics: {tr.get(\"passed\", 0)} 通过, {tr.get(\"failed\", 0)} fail')
print()

cov_result = result['evaluation']['coverage_overlap']
print('[覆盖重合度]')
print(f'  行覆盖: {cov_result[\"line_overlap_ratio\"]:.2%}')
print(f'  branch覆盖: {cov_result[\"branch_overlap_ratio\"]:.2%}')
print()

effort_result = result['evaluation']['modification_effort']
print('[改动量]')
print(f'  修改method数: {effort_result[\"total_methods\"]}')
print(f'  改动量得分: {effort_result[\"average_score\"]:.2%}')
print()

print('[综合得分]')
print(f'  最终得分: {result[\"scores\"][\"overall\"]:.2%}')
print()

print('[OpenCodeexecute]')
print(f'  耗时: {result[\"opencode_execution\"][\"duration\"]:.1f}秒')
print(f'  修改file数: {len(result[\"opencode_execution\"][\"modified_files\"])}')
"
```

### 对比不同method

如果你有多个baseline的result，可以对比：

```bash
python3 -c "
import json

# 读取OpenCoderesult
with open('/Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results_test.json') as f:
    opencode_data = json.load(f)

# 如果有其他baseline的result，也可以读取
# with open('other_baseline_results.json') as f:
#     other_data = json.load(f)

print('=== Baseline对比 ===')
print(f'OpenCode:')
scores = opencode_data['metadata']['average_scores']
print(f'  综合得分: {scores[\"avg_overall_score\"]:.2%}')
print(f'  覆盖重合度: {scores[\"avg_coverage_overlap\"]:.2%}')
print(f'  改动量得分: {scores[\"avg_modification_score\"]:.2%}')
print(f'  compilesuccess率: {scores[\"compile_success_rate\"]:.2%}')
print(f'  测试success率: {scores[\"test_success_rate\"]:.2%}')
"
```

## ⏱️ 时间效率分析

### 分析OpenCodeexecute时间

```bash
python3 -c "
import json

with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json') as f:
    summary = json.load(f)

print('=== OpenCodeexecute时间分析 ===')
print(f'总耗时: {summary[\"total_duration\"]:.1f}秒 ({summary[\"total_duration\"]/60:.1f}分钟)')
print(f'平均耗时: {summary[\"avg_duration\"]:.1f}秒/task')
print()

# 按task分析
durations = [r['duration'] for r in summary['results'] if r.get('success')]
durations.sort()

print('耗时分布:')
print(f'  最快: {min(durations):.1f}秒')
print(f'  最慢: {max(durations):.1f}秒')
print(f'  中位数: {durations[len(durations)//2]:.1f}秒')
"
```

## 📝 注意事项

1. **evaluate前确认**: 确保OpenCodeexecutecomplete且所有tasksuccess
2. **projectpath**: 确保`--project-base`指向正确的projectdirectory
3. **GT commit**: 从worktree_records.xlsx自动get
4. **evaluate时间**: evaluate过程需要compile和run测试，可能需要较长时间
5. **parallelevaluate**: 目前是串行evaluate，如需加速可以修改代码支持parallel

## 🎯 下一步

evaluatecomplete后，你可以：

1. **分析result**: 查看哪些task得分高，哪些得分低
2. **对比baseline**: 与其他method对比
3. **改进prompt**: 根据result调整prompt策略
4. **扩展dataset**: in更多project上测试
5. **发表论文**: 使用evaluateresult撰写论文

## 📞 需要帮助？

如果遇到问题：
1. 查看详细log: 使用`--verbose`parameter
2. checkworktree状态: 确认修改已save
3. validateGT commit: 确认commit hash正确
4. 测试单个task: 先evaluate一个taskvalidate流程
