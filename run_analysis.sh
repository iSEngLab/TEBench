#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/Users/mac/Desktop/java-project/tu/defects4j-projects}"
OUT="${OUT:-}"
WORKERS="${WORKERS:-}"
PHASE="${PHASE:-}"
SINCE="${SINCE:-}"
RESUME="${RESUME:-0}"
VERBOSE="${VERBOSE:-0}"

OUT_SET=0
WORKERS_SET=0
PHASE_SET=0
SINCE_SET=0
RESUME_FLAG=0
VERBOSE_FLAG=0

if [[ -n "${OUT}" ]]; then OUT_SET=1; fi
if [[ -n "${WORKERS}" ]]; then WORKERS_SET=1; fi
if [[ -n "${PHASE}" ]]; then PHASE_SET=1; fi
if [[ -n "${SINCE}" ]]; then SINCE_SET=1; fi
if [[ "${RESUME}" == "1" ]]; then RESUME_FLAG=1; fi
if [[ "${VERBOSE}" == "1" ]]; then VERBOSE_FLAG=1; fi

NOHUP_MODE=0
RUN_NOHUP="${RUN_NOHUP:-0}"

usage() {
  cat <<'EOF'
Usage: run_analysis.sh [--nohup] [--root PATH] [--out PATH] [--workers N] [--phase quick|method|full] [--since YYYY-MM-DD] [--resume] [--verbose]

Environment overrides:
  ROOT, OUT, WORKERS, PHASE, SINCE, RESUME, VERBOSE

Notes:
  - If --out/--workers/--phase/--since are not provided (or env not set),
    this script will NOT pass those flags to analysis.py, so analysis.py will
    use its own defaults (including timestamped output dirs).

Examples:
  ./run_analysis.sh
  ./run_analysis.sh --workers 8 --resume
  ./run_analysis.sh --nohup
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --nohup)
      NOHUP_MODE=1
      shift
      ;;
    --root)
      ROOT="$2"
      shift 2
      ;;
    --out)
      OUT="$2"
      OUT_SET=1
      shift 2
      ;;
    --workers)
      WORKERS="$2"
      WORKERS_SET=1
      shift 2
      ;;
    --phase)
      PHASE="$2"
      PHASE_SET=1
      shift 2
      ;;
    --since)
      SINCE="$2"
      SINCE_SET=1
      shift 2
      ;;
    --resume)
      RESUME_FLAG=1
      shift
      ;;
    --verbose)
      VERBOSE_FLAG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

LOG_BASE="${OUT:-./output/analysis}"
mkdir -p "$LOG_BASE"

if [[ "$NOHUP_MODE" == "1" && "$RUN_NOHUP" != "1" ]]; then
  ts="$(date +%Y-%m-%d_%H-%M-%S)"
  master_log="$LOG_BASE/nohup_${ts}.log"
  echo "Starting in nohup mode: $master_log"
  RUN_NOHUP=1 nohup "$0" --root "$ROOT" \
    $( [[ "$OUT_SET" == "1" ]] && echo "--out" "$OUT" ) \
    $( [[ "$WORKERS_SET" == "1" ]] && echo "--workers" "$WORKERS" ) \
    $( [[ "$PHASE_SET" == "1" ]] && echo "--phase" "$PHASE" ) \
    $( [[ "$SINCE_SET" == "1" ]] && echo "--since" "$SINCE" ) \
    $( [[ "$RESUME_FLAG" == "1" ]] && echo "--resume" ) \
    $( [[ "$VERBOSE_FLAG" == "1" ]] && echo "--verbose" ) \
    > "$master_log" 2>&1 &
  echo "PID $! running."
  exit 0
fi

projects=(
  commons-cli
  commons-codec
  commons-collections
  commons-compress
  commons-csv
  commons-jxpath
  commons-lang
  commons-math
  gson
  jackson-core
  jackson-databind
  jackson-dataformat-xml
  jfreechart
  jsoup
)

for p in "${projects[@]}"; do
  dir="$ROOT/$p"
  if [[ ! -d "$dir" ]]; then
    echo "[SKIP] $p: $dir not found"
    continue
  fi

  if [[ ! -d "$dir/.git" ]]; then
    echo "[SKIP] $p: not a git repo ($dir/.git missing)"
    continue
  fi

  if [[ ! -f "$dir/pom.xml" ]]; then
    echo "[SKIP] $p: pom.xml missing"
    continue
  fi

  ts="$(date +%Y-%m-%d_%H-%M-%S)"
  log="$LOG_BASE/log_${p}_${ts}.log"

  args=(python ./analysis.py --project "$dir")
  [[ "$OUT_SET" == "1" ]] && args+=(--output "$OUT")
  [[ "$WORKERS_SET" == "1" ]] && args+=(--workers "$WORKERS")
  [[ "$PHASE_SET" == "1" ]] && args+=(--phase "$PHASE")
  [[ "$SINCE_SET" == "1" ]] && args+=(--since "$SINCE")
  [[ "$RESUME_FLAG" == "1" ]] && args+=(--resume)
  [[ "$VERBOSE_FLAG" == "1" ]] && args+=(-v)

  echo "==> [$p] start $(date +%F' '%T)"
  if ! "${args[@]}" |& tee "$log"; then
    echo "[WARN] $p failed. See log: $log"
  fi
  echo "==> [$p] end   $(date +%F' '%T)"
done
