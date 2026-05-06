#!/usr/bin/env python3
"""
Multi-Model Runner for OpenCode (TUBench)

Drives the test-evolution task across multiple LLM backbones using the OpenCode
agent framework. Each model is run on its own isolated copy of every worktree
so that runs do not interfere with each other and can be parallelised.

This is the harness used in the TUBench paper to evaluate the four open-source
backbones reported in Table 4 (Qwen3.5, GLM-5, Kimi-K2.5, DeepSeek-V3.2),
alongside Claude Sonnet 4.6 as the closed-source reference run via OpenCode.

Usage:
    python baseline/opencode/scripts/multi_model_runner.py \
        --input /path/to/worktree_records.xlsx \
        --output /path/to/results \
        --models claude-sonnet-4-6 qwen-3.5 glm-5 kimi-k2.5 deepseek-v3.2 \
        --workers 2

The --models values are passed straight to OpenCode via `-m`. They must match
the provider/model identifiers configured in your OpenCode setup
(e.g. `myprovider/claude-sonnet-4-6`).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Resolve project root: baseline/opencode/scripts/multi_model_runner.py -> TUBench/
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is required (pip install pandas openpyxl)", file=sys.stderr)
    raise

from utils.logger import setup_logger, get_logger
from baseline.shared_test_update_prompt import format_task_prompt


# Paper-aligned defaults: the open-source backbones reported in Table 4 plus
# the closed-source reference. Replace with your provider-prefixed identifiers.
DEFAULT_MODELS = [
    "claude-sonnet-4-6",
    "qwen-3.5",
    "glm-5",
    "kimi-k2.5",
    "deepseek-v3.2",
]

OPENCODE_CMD = "opencode"


def load_worktree_records(input_path: str,
                          status_filter: Optional[List[str]] = None,
                          project_filter: Optional[List[str]] = None,
                          type_filter: Optional[List[str]] = None) -> "pd.DataFrame":
    """Load worktree records from CSV or XLSX and apply optional filters."""
    if input_path.endswith(".csv"):
        df = pd.read_csv(input_path)
    else:
        df = pd.read_excel(input_path)

    if status_filter:
        df = df[df["status"].isin(status_filter)]
    if project_filter:
        df = df[df["project"].isin(project_filter)]
    if type_filter:
        df = df[df["type"].isin(type_filter)]

    return df.reset_index(drop=True)


def build_prompt(record: dict) -> str:
    """Build the unified prompt for a single task without leaking V0 info."""
    additional_context = (
        "## Task Description\n"
        "The source code in this project has been updated (the current HEAD "
        "contains the changes).\n"
        "The test code has NOT been updated and may now be outdated.\n"
        "Your task is to first identify which tests are outdated, then update "
        "them accordingly."
    )
    return format_task_prompt(
        commit_type=record.get("type", "unknown"),
        project_name=record.get("project", "unknown"),
        additional_context=additional_context,
    )


def copy_worktree_for_model(src_worktree: str, model: str,
                            output_base: str) -> str:
    """Create an isolated copy of a worktree for a specific model run."""
    safe_model = model.replace("/", "_")
    task_name = os.path.basename(os.path.normpath(src_worktree))
    dest = os.path.join(output_base, safe_model, "worktrees", task_name)
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src_worktree, dest, symlinks=True)
    return dest


def run_single_task(task_id: int, worktree_path: str, model: str, prompt: str,
                    timeout: int, opencode_cmd: str,
                    log_dir: str) -> dict:
    """Invoke `opencode run` on one worktree for one model."""
    result = {
        "task_id": task_id,
        "model": model,
        "worktree": worktree_path,
        "success": False,
        "start_time": datetime.now().isoformat(),
        "duration": None,
        "exit_code": None,
        "error": None,
    }

    cmd = [
        opencode_cmd, "run", prompt,
        "--dir", worktree_path,
        "--format", "json",
        "-m", model,
    ]

    log_path = os.path.join(log_dir, f"task_{task_id:03d}.log")
    start = time.time()
    try:
        with open(log_path, "w", encoding="utf-8") as log_f:
            proc = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            log_f.write("=== STDOUT ===\n")
            log_f.write(proc.stdout or "")
            log_f.write("\n=== STDERR ===\n")
            log_f.write(proc.stderr or "")
        result["exit_code"] = proc.returncode
        result["success"] = proc.returncode == 0
    except subprocess.TimeoutExpired:
        result["error"] = f"Timeout after {timeout}s"
    except FileNotFoundError:
        result["error"] = f"Command not found: {opencode_cmd}"
    except Exception as exc:
        result["error"] = str(exc)

    result["duration"] = round(time.time() - start, 2)
    result["end_time"] = datetime.now().isoformat()
    return result


def run_model(model: str, records: list, output_dir: str,
              opencode_cmd: str, timeout: int, workers: int) -> dict:
    """Run all tasks for one model, returning aggregate stats."""
    logger = get_logger()
    safe_model = model.replace("/", "_")
    model_dir = os.path.join(output_dir, safe_model)
    log_dir = os.path.join(model_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"Model: {model}")
    logger.info("=" * 60)

    # Pre-stage isolated worktree copies so parallel runs do not collide.
    staged = []
    for idx, rec in enumerate(records, 1):
        src = rec.get("worktree_path") or rec.get("WorktreePath")
        if not src or not os.path.isdir(src):
            logger.warning(f"  [{idx}/{len(records)}] Skip — worktree missing: {src}")
            continue
        try:
            dest = copy_worktree_for_model(src, model, output_dir)
        except Exception as exc:
            logger.error(f"  [{idx}/{len(records)}] Copy failed for {src}: {exc}")
            continue
        staged.append((idx, rec, dest))

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for idx, rec, dest in staged:
            prompt = build_prompt(rec)
            fut = pool.submit(
                run_single_task, idx, dest, model, prompt,
                timeout, opencode_cmd, log_dir,
            )
            futures[fut] = (idx, rec)

        for fut in as_completed(futures):
            idx, rec = futures[fut]
            res = fut.result()
            res["record"] = {k: rec.get(k) for k in
                             ("project", "type", "status", "task_id", "commit")}
            results.append(res)
            tag = "OK" if res["success"] else f"FAIL ({res.get('error') or res.get('exit_code')})"
            logger.info(f"  [{idx}/{len(records)}] {model} -> {tag} "
                        f"({res['duration']}s)")

    results_path = os.path.join(model_dir, "results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    successes = sum(1 for r in results if r["success"])
    summary = {
        "model": model,
        "total": len(results),
        "successful": successes,
        "failed": len(results) - successes,
        "results_path": results_path,
    }
    logger.info(f"Saved {results_path}  ({successes}/{len(results)} succeeded)")
    return summary


def parse_args():
    p = argparse.ArgumentParser(
        description="Run TUBench tasks across multiple LLM backbones via OpenCode.")
    p.add_argument("-i", "--input", required=True,
                   help="worktree_records.xlsx (or .csv) produced by the build pipeline")
    p.add_argument("-o", "--output", required=True,
                   help="Base output directory; per-model subdirectories are created here")
    p.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                   help=f"Model identifiers passed to OpenCode -m (default: {DEFAULT_MODELS})")
    p.add_argument("--workers", type=int, default=2,
                   help="Parallel workers per model (default: 2)")
    p.add_argument("--timeout", type=int, default=1800,
                   help="Per-task timeout in seconds (default: 1800)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of tasks (useful for smoke runs)")
    p.add_argument("--projects", nargs="+", default=None,
                   help="Filter by project names (e.g. commons-csv gson)")
    p.add_argument("--types", nargs="+", default=None,
                   help="Filter by task type column")
    p.add_argument("--status", nargs="+", default=["ready"],
                   help="Filter by status column (default: ready)")
    p.add_argument("--opencode-cmd", default=OPENCODE_CMD,
                   help="Path to the opencode executable (default: opencode on PATH)")
    return p.parse_args()


def main():
    args = parse_args()
    setup_logger(level="INFO")
    logger = get_logger()

    df = load_worktree_records(
        args.input,
        status_filter=args.status,
        project_filter=args.projects,
        type_filter=args.types,
    )
    if args.limit:
        df = df.head(args.limit)

    records = df.to_dict(orient="records")
    logger.info(f"Loaded {len(records)} worktree records")
    logger.info(f"Models: {args.models}")
    logger.info(f"Workers per model: {args.workers}")

    if not records:
        logger.warning("No records to run after filtering — exiting.")
        return

    os.makedirs(args.output, exist_ok=True)

    overall = []
    for model in args.models:
        summary = run_model(
            model=model,
            records=records,
            output_dir=args.output,
            opencode_cmd=args.opencode_cmd,
            timeout=args.timeout,
            workers=args.workers,
        )
        overall.append(summary)

    summary_path = os.path.join(args.output, "multi_model_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"models": overall,
                   "generated_at": datetime.now().isoformat()},
                  f, indent=2, ensure_ascii=False)
    logger.info(f"All models complete. Summary written to {summary_path}")


if __name__ == "__main__":
    main()
