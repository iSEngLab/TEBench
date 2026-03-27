#!/bin/bash
# incommons-csv和gson上executeOpenCodebatch测试updatetask

set -e  # 遇到error立即退出

# 激活虚拟environment
source venv/bin/activate

# configurationparameter
INPUT_EXCEL="/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx"
OUTPUT_DIR="/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results"
WORKERS=2
PROJECTS="commons-csv gson"
TYPES="type1 type2"

echo "=========================================="
echo "OpenCodebatchexecute - commons-csv & gson"
echo "=========================================="
echo ""
echo "configurationinformation:"
echo "  inputfile: $INPUT_EXCEL"
echo "  output directory: $OUTPUT_DIR"
echo "  parallel数: $WORKERS"
echo "  project: $PROJECTS"
echo "  class型: $TYPES"
echo ""

# checkinputfile
if [ ! -f "$INPUT_EXCEL" ]; then
    echo "error: inputfile不存in: $INPUT_EXCEL"
    exit 1
fi

# statistics待executetask
echo "正instatistics待executetask..."
python3 -c "
import pandas as pd
df = pd.read_excel('$INPUT_EXCEL')
filtered = df[df['project'].isin(['commons-csv', 'gson'])]
ready = filtered[(filtered['status'] == 'ready') & (filtered['type'].isin(['type1', 'type2']))]
print(f'Total: {len(ready)} 个task')
print(f'  - commons-csv: {len(ready[ready[\"project\"]==\"commons-csv\"])} 个')
print(f'  - gson: {len(ready[ready[\"project\"]==\"gson\"])} 个')
print(f'  - type1: {len(ready[ready[\"type\"]==\"type1\"])} 个')
print(f'  - type2: {len(ready[ready[\"type\"]==\"type2\"])} 个')
"
echo ""

# 询问是否继续
read -p "是否继续execute? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# executebatchtask
echo ""
echo "startexecutebatchtask..."
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

# checkexecuteresult
if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "executecomplete！"
    echo "=========================================="
    echo ""
    echo "resultfile:"
    echo "  - 汇总report: $OUTPUT_DIR/summary.json"
    echo "  - 详细log: $OUTPUT_DIR/logs/"
    echo "  - Promptfile: $OUTPUT_DIR/prompts/"
    echo "  - resultfile: $OUTPUT_DIR/results/"
    echo ""

    # 显示汇总information
    if [ -f "$OUTPUT_DIR/summary.json" ]; then
        echo "execute汇总:"
        python3 -c "
import json
with open('$OUTPUT_DIR/summary.json', 'r') as f:
    summary = json.load(f)
    print(f\"  总task数: {summary['total']}")
    print(f\"  Succeeded: {summary['successful']}")
    print(f\"  Failed: {summary['failed']}")
    print(f\"  总耗时: {summary['total_duration']:.1f}秒")
    print(f\"  平均耗时: {summary['avg_duration']:.1f}秒/task")
"
    fi
else
    echo ""
    echo "=========================================="
    echo "executefail！请checklog"
    echo "=========================================="
    exit 1
fi
