# 在commons-csv和gson上执行OpenCode - 完整指南

## 📊 当前数据集状态

根据你的数据集，目前有：
- **总计**: 60个可执行任务
  - commons-csv: 52个任务
  - gson: 8个任务
- **类型分布**: type1 和 type2
- **状态**: 所有任务都是 ready 状态

## 🚀 快速开始

### 方式1: 使用自动化脚本（推荐）

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 给脚本添加执行权限
chmod +x run_opencode_batch.sh

# 执行脚本
./run_opencode_batch.sh
```

脚本会：
1. 自动激活虚拟环境
2. 显示待执行任务统计
3. 询问是否继续
4. 执行批量任务
5. 显示执行结果汇总

### 方式2: 手动执行

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 激活虚拟环境
source venv/bin/activate

# 执行批量任务
python evaluation/batch_opencode_runner.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --output /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --verbose
```

## 🧪 先测试小规模（强烈推荐）

在执行全部60个任务之前，建议先测试5个任务：

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate

# 只执行5个任务进行测试
python evaluation/batch_opencode_runner.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --output /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test \
  --workers 2 \
  --projects commons-csv gson \
  --types type1 type2 \
  --status ready \
  --limit 5 \
  --verbose
```

测试完成后检查结果：

```bash
# 查看汇总报告
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json

# 查看某个任务的日志
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/logs/task_001.log

# 查看生成的prompt
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/prompts/task_001_prompt.txt
```

## 📋 执行前检查清单

### 1. 检查OpenCode是否可用

```bash
which opencode
# 应该输出: /Users/mac/.opencode/bin/opencode
```

### 2. 检查虚拟环境

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate
python -c "import pandas; print('pandas OK')"
```

### 3. 检查数据集文件

```bash
ls -lh /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx
```

### 4. 检查worktree目录

```bash
ls /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/ | grep -E "(commons-csv|gson)" | wc -l
# 应该显示60个目录
```

### 5. 运行测试脚本

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate
python test_batch_opencode.py
```

## ⚙️ 参数说明

### 必需参数

- `--input` / `-i`: worktree_records.xlsx的路径
- `--output` / `-o`: 输出目录路径

### 过滤参数

- `--projects`: 指定项目列表（如: `commons-csv gson`）
- `--types`: 指定类型列表（如: `type1 type2`）
- `--status`: 指定状态（如: `ready`）
- `--limit`: 限制执行数量（用于测试）

### 执行参数

- `--workers`: 并行worker数量（默认2，建议2-4）
- `--timeout`: 单任务超时时间（默认1800秒=30分钟）
- `--verbose`: 显示详细日志

### OpenCode参数

- `--opencode-path`: 指定opencode路径（默认自动查找）

## 📁 输出结构

执行后会在输出目录生成：

```
opencode_results/
├── summary.json              # 汇总报告
├── prompts/                  # 生成的prompt文件
│   ├── task_001_prompt.txt
│   ├── task_002_prompt.txt
│   └── ...
├── logs/                     # 执行日志
│   ├── task_001.log
│   ├── task_002.log
│   └── ...
└── results/                  # 详细结果JSON
    ├── task_001_result.json
    ├── task_002_result.json
    └── ...
```

### summary.json 示例

```json
{
  "total": 60,
  "successful": 55,
  "failed": 5,
  "total_duration": 3600.5,
  "avg_duration": 60.0,
  "timestamp": "2026-03-03T16:00:00",
  "results": [...]
}
```

### task_XXX_result.json 示例

```json
{
  "task_id": 1,
  "worktree_path": "/path/to/worktree",
  "success": true,
  "start_time": "2026-03-03T16:00:00",
  "end_time": "2026-03-03T16:02:00",
  "duration": 120.5,
  "exit_code": 0,
  "modified_files": [
    "src/test/java/org/apache/commons/csv/CSVParserTest.java"
  ]
}
```

## 🔍 监控执行进度

### 实时查看日志

```bash
# 查看最新的日志文件
tail -f /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/logs/task_*.log
```

### 查看已完成任务数

```bash
ls /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/results/*.json | wc -l
```

### 查看成功/失败统计

```bash
cd /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results
grep -l '"success": true' results/*.json | wc -l   # 成功数
grep -l '"success": false' results/*.json | wc -l  # 失败数
```

## ⏱️ 预估执行时间

基于经验估算：
- 单个任务平均耗时: 1-3分钟
- 60个任务，2个worker并行: 约30-90分钟
- 建议预留2小时

## ❗ 常见问题

### 1. OpenCode未找到

```bash
# 检查OpenCode安装
which opencode

# 如果未安装，参考OpenCode文档安装
# 或使用--opencode-path指定路径
```

### 2. 任务超时

```bash
# 增加超时时间到1小时
--timeout 3600
```

### 3. 内存不足

```bash
# 减少并行数
--workers 1
```

### 4. 某些任务失败

```bash
# 查看失败任务的日志
cat opencode_results/logs/task_XXX.log

# 查看失败任务的详细结果
cat opencode_results/results/task_XXX_result.json
```

## 📊 执行后分析

### 1. 查看汇总统计

```bash
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/summary.json') as f:
    s = json.load(f)
    print(f'总任务: {s[\"total\"]}')
    print(f'成功: {s[\"successful\"]}')
    print(f'失败: {s[\"failed\"]}')
    print(f'成功率: {s[\"successful\"]/s[\"total\"]*100:.1f}%')
"
```

### 2. 查看修改的文件

```bash
python3 -c "
import json
import os

results_dir = '/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/results'
total_files = 0

for f in os.listdir(results_dir):
    if f.endswith('.json'):
        with open(os.path.join(results_dir, f)) as fp:
            r = json.load(fp)
            if r.get('success') and r.get('modified_files'):
                total_files += len(r['modified_files'])
                print(f'Task {r[\"task_id\"]}: {len(r[\"modified_files\"])} files')

print(f'\n总计修改文件数: {total_files}')
"
```

### 3. 检查worktree中的修改

```bash
# 查看某个worktree的修改
cd /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval
git status
git diff
```

## 🔄 重新执行失败的任务

如果有任务失败，可以单独重新执行：

```bash
# 方法1: 使用--limit和offset（需要修改脚本支持）
# 方法2: 手动处理失败的worktree
# 方法3: 修改Excel，将失败任务的status改回ready，重新执行
```

## 📝 执行记录

建议记录每次执行的信息：

```bash
# 创建执行记录
cat > /Users/mac/Desktop/TestUpdate/TUDataset/execution_log.txt << EOF
执行时间: $(date)
项目: commons-csv, gson
任务数: 60
并行数: 2
输出目录: opencode_results
状态: 执行中...
EOF
```

## 🎯 下一步

执行完成后，你可以：

1. **评估结果**: 使用evaluation模块评估修改的测试
2. **对比GT**: 将修改与V0（Ground Truth）对比
3. **计算指标**: 计算覆盖率、修改量等指标
4. **分析失败**: 分析失败任务的原因

## 📞 需要帮助？

如果遇到问题：
1. 查看详细日志: `opencode_results/logs/`
2. 查看错误信息: `opencode_results/results/`
3. 运行测试脚本: `python test_batch_opencode.py`
4. 检查OpenCode版本和配置
