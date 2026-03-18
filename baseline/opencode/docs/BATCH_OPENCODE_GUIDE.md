# Batch OpenCode Runner - 使用指南

## 概述

这个工具用于批量执行OpenCode，对数据集中的过时测试用例进行识别和更新。

## 文件说明

### 1. `evaluation/prompts.py`
定义了针对不同类型过时测试的prompt模板：
- **Type1 (Execution Error)**: 测试编译或执行失败，需要修复
- **Type2 (Coverage Gap)**: 测试可执行但覆盖率不足，需要增强
- **Generic**: 通用prompt，适用于未知类型

### 2. `evaluation/batch_opencode_runner.py`
批量执行OpenCode的主脚本，支持：
- 从Excel读取worktree记录
- 并行执行（可配置worker数量）
- 自动生成针对性prompt
- 记录执行结果和修改文件
- 不提交修改（保留在worktree中）

## 快速开始

### 1. 安装依赖

```bash
# 确保已安装pandas和openpyxl
pip install pandas openpyxl

# 确保OpenCode已安装
which opencode
```

### 2. 基本用法

```bash
# 批量执行，并行度为2
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready
```

### 3. 过滤选项

```bash
# 只处理特定项目
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --projects commons-csv gson

# 只处理特定类型
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --types type1 type2

# 限制处理数量（用于测试）
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --limit 5
```

### 4. 高级选项

```bash
# 指定OpenCode路径
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --opencode-path /custom/path/to/opencode \
  --workers 2

# 设置超时时间（秒）
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --timeout 3600

# 详细日志
python evaluation/batch_opencode_runner.py \
  -i /path/to/worktree_records.xlsx \
  -o /path/to/output \
  --workers 2 \
  --verbose
```

## 输出结构

执行后会在输出目录生成以下结构：

```
opencode_results/
├── prompts/                    # 生成的prompt文件
│   ├── task_001_prompt.txt
│   ├── task_002_prompt.txt
│   └── ...
├── logs/                       # 执行日志
│   ├── task_001.log
│   ├── task_002.log
│   └── ...
├── results/                    # 详细结果
│   ├── task_001_result.json
│   ├── task_002_result.json
│   └── ...
└── summary.json                # 汇总报告
```

### summary.json 格式

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

## Prompt设计说明

### Type1 Prompt (执行错误)

针对编译或执行失败的测试，prompt会指导OpenCode：
1. 识别编译错误和执行失败
2. 分析源代码API变更
3. 更新测试代码以匹配新API
4. 确保测试可编译和执行

### Type2 Prompt (覆盖率差距)

针对覆盖率不足的测试，prompt会指导OpenCode：
1. 识别新增或修改的源代码方法
2. 分析当前测试覆盖率
3. 增强现有测试或添加新测试
4. 提高分支覆盖率和行覆盖率

### 关键设计原则

1. **明确任务目标**: 清楚说明是修复还是增强测试
2. **提供上下文**: 说明V-1、V-0.5、V0的关系
3. **限制修改范围**: 只修改测试代码，不修改源代码
4. **保留测试意图**: 尽量保持原有测试的目的
5. **不提交修改**: 明确要求不提交，保留在worktree中

## 工作流程

### 1. 准备阶段
- 使用`batch_worktree_builder.py`创建worktree
- 每个worktree处于V-0.5状态（源代码已更新，测试未更新）

### 2. 执行阶段
- `batch_opencode_runner.py`读取worktree列表
- 为每个worktree生成针对性prompt
- 并行调用OpenCode执行测试更新
- 记录执行结果和修改内容

### 3. 评估阶段（后续）
- 在worktree中编译和运行测试
- 计算覆盖率
- 与GT（V0）对比
- 计算评估指标

## 注意事项

### 1. 并行度设置
- 建议从2开始，根据机器性能调整
- OpenCode可能占用较多资源
- 过高的并行度可能导致系统卡顿

### 2. 超时设置
- 默认1800秒（30分钟）
- 复杂项目可能需要更长时间
- 超时任务会被标记为失败

### 3. OpenCode版本
- 确保使用最新版本的OpenCode
- 不同版本的命令行参数可能不同
- 可能需要调整`run_opencode_task`中的命令

### 4. 错误处理
- 失败的任务会记录错误信息
- 可以查看logs目录下的详细日志
- 可以单独重试失败的任务

## 故障排查

### OpenCode未找到
```bash
# 检查OpenCode是否安装
which opencode

# 如果未安装，参考OpenCode文档安装
# 或使用--opencode-path指定路径
```

### pandas未安装
```bash
pip install pandas openpyxl
```

### 任务超时
```bash
# 增加超时时间
--timeout 3600  # 1小时
```

### 查看详细日志
```bash
# 使用--verbose查看详细输出
--verbose

# 或查看logs目录下的日志文件
cat opencode_results/logs/task_001.log
```

## 示例：完整工作流

```bash
# 1. 构建worktree（如果还没有）
python batch_worktree_builder.py build \
  -i /Users/mac/Desktop/TestUpdate/commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/TUDataset/worktrees \
  --projects commons-csv gson \
  --types type1 type2

# 2. 批量执行OpenCode（先测试5个）
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready \
  --limit 5 \
  --verbose

# 3. 检查结果
cat /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/summary.json

# 4. 如果测试成功，执行全部
python evaluation/batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready

# 5. 后续评估（使用其他评估工具）
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

编辑`batch_opencode_runner.py`中的`run_opencode_task`方法：

```python
cmd = [
    self.opencode_path,
    prompt,
    '--cwd', worktree_path,
    # 添加你的自定义参数
    '--your-custom-flag',
]
```

### 添加后处理

在`run_opencode_task`方法的末尾添加后处理逻辑：

```python
if result['success']:
    # 你的后处理代码
    self._post_process(worktree_path, result)
```

## 参考资料

- OpenCode文档: [链接]
- TUBench项目文档: `README.md`
- Worktree管理: `evaluation/worktree_manager.py`
- 评估框架: `evaluation/evaluation_orchestrator.py`
