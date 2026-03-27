#!/bin/bash
# 完整experiment流程script - 构建worktree + run3个agent
#
# 使用method:
#   # 1. 先构建所有agent的worktree
#   bash baseline/run_experiment.sh build
#
#   # 2. 分别run各agent
#   bash baseline/run_experiment.sh run opencode
#   bash baseline/run_experiment.sh run claude-code
#   bash baseline/run_experiment.sh run codex
#
#   # 3. 查看statistics
#   bash baseline/run_experiment.sh stats
#   # 4. validateworktree可compile/可测试
#   bash baseline/run_experiment.sh verify codex

set -e

# ============ configuration ============
INPUT_CSV="/home/yeren/docker-env/filtered_commits_step2_full.csv"
BASE_DIR="/home/yeren/docker-env/TUDataset/agents"
SOURCE_REPOS="/home/yeren/docker-env/TUDataset/defects4j-projects"
WORKERS=3
TIMEOUT=1800
CODEX_DEFAULT_MODEL="gpt-5.3-codex"
OPENCODE_DEFAULT_MODEL="myprovider/claude-sonnet-4-6"
# 统一使用 Maven default中央本地仓库（通常 ~/.m2/repository）
# 如需覆盖，可in命令行显式传 --maven-repo-local

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ============ 函数 ============

show_help() {
    echo "TUBench experiment流程script"
    echo ""
    echo "用法:"
    echo "  bash baseline/run_experiment.sh <command> [options]"
    echo ""
    echo "命令:"
    echo "  build [agents...]       构建worktree (default全部: opencode claude-code codex)"
    echo "  run <agent> [options]   run指定agent的batchtask"
    echo "  verify <agent> [opts]   对worktreebatchexecute mvn compile/test"
    echo "  stats [agents...]       查看statistics"
    echo "  clean [agents...]       clean upworktree"
    echo ""
    echo "Example:"
    echo "  bash baseline/run_experiment.sh build                    # 构建全部"
    echo "  bash baseline/run_experiment.sh build claude-code codex  # 只构建指定agent"
    echo "  bash baseline/run_experiment.sh run claude-code          # runclaude-code"
    echo "  bash baseline/run_experiment.sh run codex --limit 5      # runcodex前5个"
    echo "  bash baseline/run_experiment.sh run codex --model o3     # 指定codexmodel"
    echo "  bash baseline/run_experiment.sh verify codex --prewarm-only  # 仅预热defaultMaven仓库"
    echo "  bash baseline/run_experiment.sh verify codex             # 校验codex worktrees"
    echo "  bash baseline/run_experiment.sh run opencode --projects commons-csv"
    echo "  bash baseline/run_experiment.sh stats                    # 查看全部statistics"
}

cmd_build() {
    local agents="${@:-opencode claude-code codex}"
    echo "=========================================="
    echo "构建Worktreeenvironment"
    echo "  input: $INPUT_CSV"
    echo "  基础directory: $BASE_DIR"
    echo "  源仓库: $SOURCE_REPOS"
    echo "  Agents: $agents"
    echo "=========================================="

    cd "$PROJECT_ROOT"
    python3 baseline/build_worktrees.py --verbose build \
        --input "$INPUT_CSV" \
        --base-dir "$BASE_DIR" \
        --source-repos "$SOURCE_REPOS" \
        --build-mode branch \
        --agents $agents
}

cmd_run() {
    local agent="$1"
    shift || true

    if [ -z "$agent" ]; then
        echo "error: 请指定agent (opencode / claude-code / codex)"
        exit 1
    fi

    local records="$BASE_DIR/$agent/worktree_records.csv"
    local output="$BASE_DIR/$agent/results"

    if [ ! -f "$records" ]; then
        echo "error: recordfile不存in: $records"
        echo "请先run: bash baseline/run_experiment.sh build $agent"
        exit 1
    fi

    echo "=========================================="
    echo "run $agent"
    echo "  record: $records"
    echo "  output: $output"
    echo "  Workers: $WORKERS"
    echo "=========================================="

    cd "$PROJECT_ROOT"

    case "$agent" in
        opencode)
            local has_model=0
            local arg
            for arg in "$@"; do
                if [ "$arg" = "--model" ] || [ "$arg" = "-m" ]; then
                    has_model=1
                    break
                fi
            done
            if [ "$has_model" -eq 1 ]; then
                python baseline/opencode/scripts/batch_opencode_runner.py \
                    -i "$records" -o "$output" \
                    --workers $WORKERS --timeout $TIMEOUT \
                    --status ready \
                    "$@"
            else
                python baseline/opencode/scripts/batch_opencode_runner.py \
                    -i "$records" -o "$output" \
                    --workers $WORKERS --timeout $TIMEOUT \
                    --status ready \
                    --model "$OPENCODE_DEFAULT_MODEL" \
                    "$@"
            fi
            ;;
        claude-code)
            python baseline/claude-code/scripts/batch_claude_runner.py \
                -i "$records" -o "$output" \
                --workers $WORKERS --timeout $TIMEOUT \
                --status ready \
                "$@"
            ;;
        codex)
            local has_model=0
            local arg
            for arg in "$@"; do
                if [ "$arg" = "--model" ] || [ "$arg" = "-m" ]; then
                    has_model=1
                    break
                fi
            done
            if [ "$has_model" -eq 1 ]; then
                python baseline/codex/scripts/batch_codex_runner.py \
                    -i "$records" -o "$output" \
                    --workers $WORKERS --timeout $TIMEOUT \
                    --status ready \
                    "$@"
            else
                python baseline/codex/scripts/batch_codex_runner.py \
                    -i "$records" -o "$output" \
                    --workers $WORKERS --timeout $TIMEOUT \
                    --status ready \
                    --model "$CODEX_DEFAULT_MODEL" \
                    "$@"
            fi
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

cmd_verify() {
    local agent="$1"
    shift || true

    if [ -z "$agent" ]; then
        echo "error: 请指定agent (opencode / claude-code / codex)"
        exit 1
    fi

    local records="$BASE_DIR/$agent/worktree_records.csv"
    local output="$BASE_DIR/$agent/verify_maven_results.json"

    if [ ! -f "$records" ]; then
        echo "error: recordfile不存in: $records"
        echo "请先run: bash baseline/run_experiment.sh build $agent"
        exit 1
    fi

    echo "=========================================="
    echo "validate $agent worktrees (mvn compile/test)"
    echo "  record: $records"
    echo "  output: $output"
    echo "  Maven Repo: default (~/.m2/repository)"
    echo "=========================================="

    cd "$PROJECT_ROOT"
    python baseline/verify_worktrees_maven.py \
        --records "$records" \
        --output "$output" \
        "$@"
}

# ============ 主入口 ============
command="${1:-help}"
shift || true

case "$command" in
    build)  cmd_build "$@" ;;
    run)    cmd_run "$@" ;;
    verify) cmd_verify "$@" ;;
    stats)  cmd_stats "$@" ;;
    clean)  cmd_clean "$@" ;;
    help|--help|-h) show_help ;;
    *)
        echo "未知命令: $command"
        show_help
        exit 1
        ;;
esac
