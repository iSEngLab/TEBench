#!/bin/bash
# 完整实验流程脚本 - 构建worktree + 运行3个agent
#
# 使用方法:
#   # 1. 先构建所有agent的worktree
#   bash baseline/run_experiment.sh build
#
#   # 2. 分别运行各agent
#   bash baseline/run_experiment.sh run opencode
#   bash baseline/run_experiment.sh run claude-code
#   bash baseline/run_experiment.sh run codex
#
#   # 3. 查看统计
#   bash baseline/run_experiment.sh stats

set -e

# ============ 配置 ============
INPUT_CSV="/Users/mac/Desktop/TestUpdate/filtered_commits_step2_full.csv"
BASE_DIR="/Users/mac/Desktop/TestUpdate/TUDataset/agents"
SOURCE_REPOS="/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects-1"
WORKERS=3
TIMEOUT=1800

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ============ 函数 ============

show_help() {
    echo "TUBench 实验流程脚本"
    echo ""
    echo "用法:"
    echo "  bash baseline/run_experiment.sh <command> [options]"
    echo ""
    echo "命令:"
    echo "  build [agents...]       构建worktree (默认全部: opencode claude-code codex)"
    echo "  run <agent> [options]   运行指定agent的批量任务"
    echo "  stats [agents...]       查看统计信息"
    echo "  clean [agents...]       清理worktree"
    echo ""
    echo "示例:"
    echo "  bash baseline/run_experiment.sh build                    # 构建全部"
    echo "  bash baseline/run_experiment.sh build claude-code codex  # 只构建指定agent"
    echo "  bash baseline/run_experiment.sh run claude-code          # 运行claude-code"
    echo "  bash baseline/run_experiment.sh run codex --limit 5      # 运行codex前5个"
    echo "  bash baseline/run_experiment.sh run opencode --projects commons-csv"
    echo "  bash baseline/run_experiment.sh stats                    # 查看全部统计"
}

cmd_build() {
    local agents="${@:-opencode claude-code codex}"
    echo "=========================================="
    echo "构建Worktree环境"
    echo "  输入: $INPUT_CSV"
    echo "  基础目录: $BASE_DIR"
    echo "  源仓库: $SOURCE_REPOS"
    echo "  Agents: $agents"
    echo "=========================================="

    cd "$PROJECT_ROOT"
    python3 baseline/build_worktrees.py --verbose build \
        --input "$INPUT_CSV" \
        --base-dir "$BASE_DIR" \
        --source-repos "$SOURCE_REPOS" \
        --agents $agents
}

cmd_run() {
    local agent="$1"
    shift || true

    if [ -z "$agent" ]; then
        echo "错误: 请指定agent (opencode / claude-code / codex)"
        exit 1
    fi

    local records="$BASE_DIR/$agent/worktree_records.csv"
    local output="$BASE_DIR/$agent/results"

    if [ ! -f "$records" ]; then
        echo "错误: 记录文件不存在: $records"
        echo "请先运行: bash baseline/run_experiment.sh build $agent"
        exit 1
    fi

    echo "=========================================="
    echo "运行 $agent"
    echo "  记录: $records"
    echo "  输出: $output"
    echo "  Workers: $WORKERS"
    echo "=========================================="

    cd "$PROJECT_ROOT"

    case "$agent" in
        opencode)
            python baseline/opencode/scripts/batch_opencode_runner.py \
                -i "$records" -o "$output" \
                --workers $WORKERS --timeout $TIMEOUT \
                --status ready \
                "$@"
            ;;
        claude-code)
            python baseline/claude-code/scripts/batch_claude_runner.py \
                -i "$records" -o "$output" \
                --workers $WORKERS --timeout $TIMEOUT \
                --status ready \
                "$@"
            ;;
        codex)
            python baseline/codex/scripts/batch_codex_runner.py \
                -i "$records" -o "$output" \
                --workers $WORKERS --timeout $TIMEOUT \
                --status ready \
                "$@"
            ;;
        *)
            echo "未知agent: $agent (可选: opencode / claude-code / codex)"
            exit 1
            ;;
    esac
}

cmd_stats() {
    local agents="${@:-opencode claude-code codex}"
    cd "$PROJECT_ROOT"
    python3 baseline/build_worktrees.py stats \
        --base-dir "$BASE_DIR" \
        --agents $agents
}

cmd_clean() {
    local agents="${@:-opencode claude-code codex}"
    cd "$PROJECT_ROOT"
    python3 baseline/build_worktrees.py clean \
        --base-dir "$BASE_DIR" \
        --agents $agents
}

# ============ 主入口 ============
command="${1:-help}"
shift || true

case "$command" in
    build)  cmd_build "$@" ;;
    run)    cmd_run "$@" ;;
    stats)  cmd_stats "$@" ;;
    clean)  cmd_clean "$@" ;;
    help|--help|-h) show_help ;;
    *)
        echo "未知命令: $command"
        show_help
        exit 1
        ;;
esac
