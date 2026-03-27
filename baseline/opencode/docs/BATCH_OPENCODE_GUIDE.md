# Batch OpenCode Runner - 使用指南

## 概述

这个工具用于batchexecuteOpenCode，对dataset中的obsolete test cases进行identify和update。

## filedescription

### 1. `evaluation/prompts.py`
定义了针对不同class型obsolete tests的prompt模板：
- **Type1 (Execution Error)**: 测试compile或executefail，需要修复
- **Type2 (Coverage Gap)**: 测试可execute但coverage不足，需要增强
- **Generic**: 通用prompt，适用于未知class型

### 2. `evaluation/batch_opencode_runner.py`
batchexecuteOpenCode的主script，支持：
- 从Excel读取worktreerecord
- parallelexecute（可configurationworker数量）
- 自动generate针对性prompt
- recordexecuteresult和修改file
- 不commit修改（保留inworktree中）

## 快速start

### 1. 安装依赖

```bash
# 确保已安装pandas和openpyxl
pip install pandas openpyxl

# 确保OpenCode已安装
which opencode
```

### 2. 基本用法

```bash
# batchexecute，parallel度为2
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready
```

### 3. 过滤选项

```bash
# 只process特定project
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --projects commons-csv gson

# 只process特定class型
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --types type1 type2

# 限制process数量（用于测试）
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --limit 5
```

### 4. advanced options

```bash
# 指定OpenCodepath
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --opencode-path /custom/path/to/opencode \
  --workers 2

# 设置timeout时间（秒）
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --timeout 3600

# 详细log
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --verbose
```

## output结构

execute后会inoutput directorygenerate以下结构：

```
opencode_results/
├── prompts/                    # generate的promptfile
│   ├── task_001_prompt.txt
│   ├── task_002_prompt.txt
│   └── ...
├── logs/                       # executelog
│   ├── task_001.log
│   ├── task_002.log
│   └── ...
├── results/                    # 详细result
│   ├── task_001_result.json
│   ├── task_002_result.json
│   └── ...
└── summary.json                # 汇总report
```

### summary.json format

```json
{
  "total": 10,
  "successful": 8,
  "failed": 2,
  "total_duration": 1234.5,
  "avg_duration": 123.45,
  "timestamp": "2026-03-03T15:30:00",
  "results": [
    {
      "task_id": 1,
      "worktree_path": "/path/to/worktree",
      "success": true,
      "duration": 120.5,
      "modified_files": [
        "src/test/java/com/example/TestClass.java"
      ],
      "exit_code": 0
    }
  ]
}
```

## Prompt设计description

### Type1 Prompt (executeerror)

针对compile或executefail的测试，prompt会指导OpenCode：
1. identifycompileerror和executefail
2. 分析source codeAPI变更
3. updatetest code以匹配新API
4. 确保测试可compile和execute

### Type2 Prompt (coverage差距)

针对coverage不足的测试，prompt会指导OpenCode：
1. identify新增或修改的source codemethod
2. 分析当前测试coverage
3. 增强现有测试或添加新测试
4. 提高branchcoverage和行coverage

### 关键设计原则

1. **明确task目标**: 清楚description是修复还是增强测试
2. **提供上下文**: descriptionV-1、V-0.5、V0的关系
3. **限制修改范围**: 只修改test code，不修改source code
4. **保留测试意图**: 尽量保持原有测试的目的
5. **不commit修改**: 明确要求不commit，保留inworktree中

## workflow程

### 1. 准备phase
- 使用`batch_worktree_builder.py`createworktree
- 每个worktree处于V-0.5状态（source code已update，测试未update）

### 2. executephase
- `batch_opencode_runner.py`读取worktree列表
- 为每个worktreegenerate针对性prompt
- parallel调用OpenCodeexecute测试update
- recordexecuteresult和修改内容

### 3. evaluatephase（后续）
- inworktree中compile和run测试
- calculatecoverage
- 与GT（V0）对比
- calculateevaluate指标

## 注意事项

### 1. parallel度设置
- 建议从2start，根据机器性能调整
- OpenCode可能占用较多资源
- 过高的parallel度可能导致系统卡顿

### 2. timeout设置
- default1800秒（30分钟）
- 复杂project可能需要更长时间
- timeouttask会被标记为fail

### 3. OpenCodeversion
- 确保使用最新version的OpenCode
- 不同version的命令行parameter可能不同
- 可能需要调整`run_opencode_task`中的命令

### 4. errorprocess
- fail的task会recorderrorinformation
- 可以查看logsdirectory下的详细log
- 可以单独重试fail的task

## 故障排查

### OpenCode未found
```bash
# checkOpenCode是否安装
which opencode

# 如果未安装，参考OpenCode文档安装
# 或使用--opencode-path指定path
```

### pandas未安装
```bash
pip install pandas openpyxl
```

### tasktimeout
```bash
# 增加timeout时间
--timeout 3600  # 1小时
```

### 查看详细log
```bash
# 使用--verbose查看详细output
--verbose

# 或查看logsdirectory下的logfile
cat opencode_results/logs/task_001.log
```

## example：完整workflow

```bash
# 1. 构建worktree（如果还没有）
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-csv gson \
  --types type1 type2

# 2. batchexecuteOpenCode（先测试5个）
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready \
  --limit 5 \
  --verbose

# 3. checkresult
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/summary.json

# 4. 如果测试success，execute全部
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready

# 5. 后续evaluate（使用其他evaluate工具）
# ...
```

## 扩展和定制

### 自定义Prompt

编辑`evaluation/prompts.py`中的prompt模板：

```python
TYPE1_PROMPT = """
# 你的自定义prompt
...
"""
```

### 调整OpenCode命令

编辑`batch_opencode_runner.py`中的`run_opencode_task`method：

```python
cmd = [
    self.opencode_path,
    prompt,
    '--cwd', worktree_path,
    # 添加你的自定义parameter
    '--your-custom-flag',
]
```

### 添加后process

in`run_opencode_task`method的末尾添加后process逻辑：

```python
if result['success']:
    # 你的后process代码
    self._post_process(worktree_path, result)
```

## 参考资料

- OpenCode文档: [链接]
- TUBenchproject文档: `README.md`
- Worktree管理: `evaluation/worktree_manager.py`
- evaluate框架: `evaluation/evaluation_orchestrator.py`
