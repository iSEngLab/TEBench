#!/bin/bash
#
# Top-level driver for the TUBench coding-agent experiments.
#
# Examples:
#   bash baseline/run_experiment.sh build
#   bash baseline/run_experiment.sh run opencode
#   bash baseline/run_experiment.sh run claude-code
#   bash baseline/run_experiment.sh run codex
#   bash baseline/run_experiment.sh stats
#   bash baseline/run_experiment.sh verify codex

set -e

# ============ Configuration ============
INPUT_CSV="/home/yeren/docker-env/filtered_commits_step2_full.csv"
BASE_DIR="/home/yeren/docker-env/TUDataset/agents"
SOURCE_REPOS="/home/yeren/docker-env/TUDataset/defects4j-projects"
WORKERS=3
TIMEOUT=1800
CODEX_DEFAULT_MODEL="gpt-5.3-codex"
OPENCODE_DEFAULT_MODEL="myprovider/claude-sonnet-4-6"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
# =======================================

show_help() {
    echo "TUBench experiment driver"
    echo ""
    echo "Usage:"
    echo "  bash baseline/run_experiment.sh <command> [options]"
    echo ""
    echo "Commands:"
    echo "  build  [agents...]      Build worktrees (default: opencode claude-code codex)"
    echo "  run    <agent> [opts]   Run an agent's batch task"
    echo "  verify <agent> [opts]   Run mvn compile/test over agent worktrees"
    echo "  stats  [agents...]      Print worktree statistics"
    echo "  clean  [agents...]      Remove agent worktrees"
    echo ""
    echo "Examples:"
    echo "  bash baseline/run_experiment.sh build"
    echo "  bash baseline/run_experiment.sh build claude-code codex"
    echo "  bash baseline/run_experiment.sh run claude-code"
    echo "  bash baseline/run_experiment.sh run codex --limit 5"
    echo "  bash baseline/run_experiment.sh run codex --model o3"
    echo "  bash baseline/run_experiment.sh verify codex --prewarm-only"
    echo "  bash baseline/run_experiment.sh verify codex"
    echo "  bash baseline/run_experiment.sh run opencode --projects commons-csv"
    echo "  bash baseline/run_experiment.sh stats"
}

cmd_build() {
    local agents="${@:-opencode claude-code codex}"
    echo "=========================================="
    echo "Building worktrees"
    echo "  input:        $INPUT_CSV"
    echo "  base-dir:     $BASE_DIR"
    echo "  source-repos: $SOURCE_REPOS"
    echo "  agents:       $agents"
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
        echo "Error: missing agent (opencode / claude-code / codex)"
        exit 1
    fi

    local records="$BASE_DIR/$agent/worktree_records.csv"
    local output="$BASE_DIR/$agent/results"

    if [ ! -f "$records" ]; then
        echo "Error: records file not found: $records"
        echo "Run first: bash baseline/run_experiment.sh build $agent"
        exit 1
    fi

    echo "=========================================="
    echo "Running $agent"
    echo "  records: $records"
    echo "  output:  $output"
    echo "  workers: $WORKERS"
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
            echo "Unknown agent: $agent (expected opencode / claude-code / codex)"
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
        echo "Error: missing agent (opencode / claude-code / codex)"
        exit 1
    fi

    local records="$BASE_DIR/$agent/worktree_records.csv"
    local output="$BASE_DIR/$agent/verify_maven_results.json"

    if [ ! -f "$records" ]; then
        echo "Error: records file not found: $records"
        echo "Run first: bash baseline/run_experiment.sh build $agent"
        exit 1
    fi

    echo "=========================================="
    echo "Verifying $agent worktrees (mvn compile/test)"
    echo "  records: $records"
    echo "  output:  $output"
    echo "  maven repo: default (~/.m2/repository)"
    echo "=========================================="

    cd "$PROJECT_ROOT"
    python baseline/verify_worktrees_maven.py \
        --records "$records" \
        --output "$output" \
        "$@"
}

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
        echo "Unknown command: $command"
        show_help
        exit 1
        ;;
esac
