#!/bin/bash
# 在commons-csv和gson上执行OpenCode批量测试更新任务

set -e  # 遇到错误立即退出

# 激活虚拟环境
source venv/bin/activate

# 配置参数
INPUT_EXCEL="/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx"
OUTPUT_DIR="/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results"
WORKERS=2
PROJECTS="commons-csv gson"
TYPES="type1 type2"

echo "=========================================="
echo "OpenCode批量执行 - commons-csv & gson"
echo "=========================================="
echo ""
echo "配置信息:"
echo "  输入文件: $INPUT_EXCEL"
echo "  输出目录: $OUTPUT_DIR"
echo "  并行数: $WORKERS"
echo "  项目: $PROJECTS"
echo "  类型: $TYPES"
echo ""

# 检查输入文件
if [ ! -f "$INPUT_EXCEL" ]; then
    echo "错误: 输入文件不存在: $INPUT_EXCEL"
    exit 1
fi

# 统计待执行任务
echo "正在统计待执行任务..."
python3 -c "
import pandas as pd
df = pd.read_excel('$INPUT_EXCEL')
filtered = df[df['project'].isin(['commons-csv', 'gson'])]
ready = filtered[(filtered['status'] == 'ready') & (filtered['type'].isin(['type1', 'type2']))]
print(f'总计: {len(ready)} 个任务')
print(f'  - commons-csv: {len(ready[ready[\"project\"]==\"commons-csv\"])} 个')
print(f'  - gson: {len(ready[ready[\"project\"]==\"gson\"])} 个')
print(f'  - type1: {len(ready[ready[\"type\"]==\"type1\"])} 个')
print(f'  - type2: {len(ready[ready[\"type\"]==\"type2\"])} 个')
"
echo ""

# 询问是否继续
read -p "是否继续执行? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 执行批量任务
echo ""
echo "开始执行批量任务..."
echo "=========================================="
echo ""

python evaluation/batch_opencode_runner.py \
  --input "$INPUT_EXCEL" \
  --output "$OUTPUT_DIR" \
  --workers $WORKERS \
  --projects $PROJECTS \
  --types $TYPES \
  --status ready \
  --verbose

# 检查执行结果
if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "执行完成！"
    echo "=========================================="
    echo ""
    echo "结果文件:"
    echo "  - 汇总报告: $OUTPUT_DIR/summary.json"
    echo "  - 详细日志: $OUTPUT_DIR/logs/"
    echo "  - Prompt文件: $OUTPUT_DIR/prompts/"
    echo "  - 结果文件: $OUTPUT_DIR/results/"
    echo ""

    # 显示汇总信息
    if [ -f "$OUTPUT_DIR/summary.json" ]; then
        echo "执行汇总:"
        python3 -c "
import json
with open('$OUTPUT_DIR/summary.json', 'r') as f:
    summary = json.load(f)
    print(f\"  总任务数: {summary['total']}")
    print(f\"  成功: {summary['successful']}")
    print(f\"  失败: {summary['failed']}")
    print(f\"  总耗时: {summary['total_duration']:.1f}秒")
    print(f\"  平均耗时: {summary['avg_duration']:.1f}秒/任务")
"
    fi
else
    echo ""
    echo "=========================================="
    echo "执行失败！请检查日志"
    echo "=========================================="
    exit 1
fi
