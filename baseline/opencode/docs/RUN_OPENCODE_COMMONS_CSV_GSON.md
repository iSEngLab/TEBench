# incommons-csv和gson上executeOpenCode - 完整指南

## 📊 当前dataset状态

根据你的dataset，目前有：
- **total**: 60个可executetask
  - commons-csv: 52个task
  - gson: 8个task
- **class型分布**: type1 和 type2
- **状态**: 所有task都是 ready 状态

## 🚀 快速start

### 方式1: 使用自动化script（推荐）

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 给script添加execute权限
chmod +x run_opencode_batch.sh

# executescript
./run_opencode_batch.sh
```

script会：
1. 自动激活虚拟environment
2. 显示待executetaskstatistics
3. 询问是否继续
4. executebatchtask
5. 显示executeresult汇总

### 方式2: 手动execute

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench

# 激活虚拟environment
source venv/bin/activate

# executebatchtask
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

inexecute全部60个task之前，建议先测试5个task：

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate

# 只execute5个task进行测试
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

测试complete后checkresult：

```bash
# 查看汇总report
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/summary.json

# 查看某个task的log
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/logs/task_001.log

# 查看generate的prompt
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test/prompts/task_001_prompt.txt
```

## 📋 execute前check清单

### 1. checkOpenCode是否可用

```bash
which opencode
# 应该output: /Users/mac/.opencode/bin/opencode
```

### 2. check虚拟environment

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate
python -c "import pandas; print('pandas OK')"
```

### 3. checkdataset file

```bash
ls -lh /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx
```

### 4. checkworktreedirectory

```bash
ls /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/ | grep -E "(commons-csv|gson)" | wc -l
# 应该显示60个directory
```

### 5. run测试script

```bash
cd /Users/mac/Desktop/TestUpdate/TUBench
source venv/bin/activate
python test_batch_opencode.py
```

## ⚙️ parameterdescription

### 必需parameter

- `--input` / `-i`: worktree_records.xlsx的path
- `--output` / `-o`: output directorypath

### 过滤parameter

- `--projects`: 指定project列表（如: `commons-csv gson`）
- `--types`: 指定class型列表（如: `type1 type2`）
- `--status`: 指定状态（如: `ready`）
- `--limit`: 限制execute数量（用于测试）

### executeparameter

- `--workers`: number of parallel workers（default2，建议2-4）
- `--timeout`: 单tasktimeout时间（default1800秒=30分钟）
- `--verbose`: 显示详细log

### OpenCodeparameter

- `--opencode-path`: 指定opencodepath（default自动查找）

## 📁 output结构

execute后会inoutput directorygenerate：

```
opencode_results/
├── summary.json              # 汇总report
├── prompts/                  # generate的promptfile
│   ├── task_001_prompt.txt
│   ├── task_002_prompt.txt
│   └── ...
├── logs/                     # executelog
│   ├── task_001.log
│   ├── task_002.log
│   └── ...
└── results/                  # 详细resultJSON
    ├── task_001_result.json
    ├── task_002_result.json
    └── ...
```

### summary.json example

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

### task_XXX_result.json example

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

## 🔍 监控execute进度

### 实时查看log

```bash
# 查看最新的logfile
tail -f /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/logs/task_*.log
```

### 查看已completetask数

```bash
ls /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/results/*.json | wc -l
```

### 查看success/failstatistics

```bash
cd /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results
grep -l '"success": true' results/*.json | wc -l   # success数
grep -l '"success": false' results/*.json | wc -l  # fail数
```

## ⏱️ 预估execute时间

基于经验估算：
- 单个task平均耗时: 1-3分钟
- 60个task，2个workerparallel: 约30-90分钟
- 建议预留2小时

## ❗ 常见问题

### 1. OpenCode未found

```bash
# checkOpenCode安装
which opencode

# 如果未安装，参考OpenCode文档安装
# 或使用--opencode-path指定path
```

### 2. tasktimeout

```bash
# 增加timeout时间到1小时
--timeout 3600
```

### 3. 内存不足

```bash
# 减少parallel数
--workers 1
```

### 4. 某些taskfail

```bash
# 查看failtask的log
cat opencode_results/logs/task_XXX.log

# 查看failtask的详细result
cat opencode_results/results/task_XXX_result.json
```

## 📊 execute后分析

### 1. 查看汇总statistics

```bash
python3 -c "
import json
with open('/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/summary.json') as f:
    s = json.load(f)
    print(f'总task: {s[\"total\"]}')
    print(f'Succeeded: {s[\"successful\"]}')
    print(f'Failed: {s[\"failed\"]}')
    print(f'success率: {s[\"successful\"]/s[\"total\"]*100:.1f}%')
"
```

### 2. 查看修改的file

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

print(f'\ntotal修改file数: {total_files}')
"
```

### 3. checkworktree中的修改

```bash
# 查看某个worktree的修改
cd /Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval
git status
git diff
```

## 🔄 重新executefail的task

如果有taskfail，可以单独重新execute：

```bash
# method1: 使用--limit和offset（需要修改script支持）
# method2: 手动processfail的worktree
# method3: 修改Excel，将failtask的status改回ready，重新execute
```

## 📝 executerecord

建议record每次execute的information：

```bash
# createexecuterecord
cat > /Users/mac/Desktop/TestUpdate/TUDataset/execution_log.txt << EOF
execute时间: $(date)
project: commons-csv, gson
task数: 60
parallel数: 2
output directory: opencode_results
状态: execute中...
EOF
```

## 🎯 下一步

executecomplete后，你可以：

1. **evaluateresult**: 使用evaluation模块evaluate修改的测试
2. **对比GT**: 将修改与V0（Ground Truth）对比
3. **calculate指标**: calculatecoverage、修改量等指标
4. **分析fail**: 分析failtask的原因

## 📞 需要帮助？

如果遇到问题：
1. 查看详细log: `opencode_results/logs/`
2. 查看errorinformation: `opencode_results/results/`
3. run测试script: `python test_batch_opencode.py`
4. checkOpenCodeversion和configuration
