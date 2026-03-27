#!/usr/bin/env python3
"""
Batch evaluate worktrees from a CSV record file.

Reads rows from worktree_records.csv, runs TUBench evaluation for each worktree,
saves per-task JSON results, and writes a summary CSV with score columns.
Coverage is exported as separate line/branch overlap columns.
"""

import csv
import json
import os
import sys
import argparse
from datetime import datetime
from typing import Any, Dict, List


# baseline/opencode/scripts/batch_evaluate_worktrees_from_csv.py -> TUBench/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCODE_DIR = os.path.dirname(SCRIPT_DIR)
BASELINE_DIR = os.path.dirname(OPENCODE_DIR)
PROJECT_ROOT = os.path.dirname(BASELINE_DIR)
sys.path.insert(0, PROJECT_ROOT)

from update_evaluation import EvaluationOrchestrator
from utils.logger import setup_logger, get_logger


DEFAULT_RECORDS = "/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv"
DEFAULT_OUTPUT_DIR = "/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results/evaluate"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _load_records(csv_file: str, only_ready: bool = True) -> List[Dict[str, str]]:
    required = {"task_id", "project", "project_path", "worktree_path", "v_0_commit"}
    rows: List[Dict[str, str]] = []

    with open(csv_file, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        missing = required - headers
        if missing:
            raise ValueError(f"CSV缺少必要列: {sorted(missing)}")

        for row in reader:
            if only_ready and (row.get("status") or "").strip().lower() != "ready":
                continue
            rows.append(row)

    return rows


def _result_filename(project: str, task_id: str) -> str:
    task = str(task_id).strip()
    return f"{project}-task_{task}_evaluation.json"


def run_batch(records_file: str, output_dir: str, only_ready: bool, limit: int = 0) -> Dict[str, Any]:
    logger = get_logger()
    os.makedirs(output_dir, exist_ok=True)

    rows = _load_records(records_file, only_ready=only_ready)
    if limit and limit > 0:
        rows = rows[:limit]

    logger.info(f"读取到 {len(rows)} 条待evaluaterecord")

    orchestrators: Dict[str, EvaluationOrchestrator] = {}
    summary_rows: List[Dict[str, Any]] = []
    batch_results: List[Dict[str, Any]] = []
    successful = 0
    failed = 0

    for idx, row in enumerate(rows, start=1):
        task_id = str(row.get("task_id", "")).strip()
        project = str(row.get("project", "unknown")).strip()
        project_path = str(row.get("project_path", "")).strip()
        worktree_path = str(row.get("worktree_path", "")).strip()
        gt_commit = str(row.get("v_0_commit", "")).strip()

        logger.info(f"[{idx}/{len(rows)}] evaluate {project} task {task_id} ({gt_commit[:8]})")

        result_json_name = _result_filename(project, task_id)
        result_json_path = os.path.join(output_dir, result_json_name)

        if not project_path or not os.path.exists(project_path):
            error = f"project_path不存in: {project_path}"
            logger.error(error)
            eval_result = {
                "success": False,
                "project": project,
                "gt_commit": gt_commit,
                "task_id": task_id,
                "error": error,
                "scores": {
                    "executability": 0.0,
                    "coverage_overlap": 0.0,
                    "modification_score": 0.0,
                    "overall": 0.0,
                },
            }
        elif not worktree_path or not os.path.exists(worktree_path):
            error = f"worktree_path不存in: {worktree_path}"
            logger.error(error)
            eval_result = {
                "success": False,
                "project": project,
                "gt_commit": gt_commit,
                "task_id": task_id,
                "error": error,
                "scores": {
                    "executability": 0.0,
                    "coverage_overlap": 0.0,
                    "modification_score": 0.0,
                    "overall": 0.0,
                },
            }
        elif not gt_commit:
            error = "v_0_commit为空"
            logger.error(error)
            eval_result = {
                "success": False,
                "project": project,
                "gt_commit": gt_commit,
                "task_id": task_id,
                "error": error,
                "scores": {
                    "executability": 0.0,
                    "coverage_overlap": 0.0,
                    "modification_score": 0.0,
                    "overall": 0.0,
                },
            }
        else:
            if project_path not in orchestrators:
                orchestrators[project_path] = EvaluationOrchestrator(project_path)

            orchestrator = orchestrators[project_path]
            eval_result = orchestrator.run_evaluation(worktree_path, gt_commit)
            eval_result["task_id"] = task_id
            eval_result["project"] = project
            eval_result["project_path"] = project_path
            eval_result["worktree_path"] = worktree_path

        with open(result_json_path, "w", encoding="utf-8") as f:
            json.dump(eval_result, f, indent=2, ensure_ascii=False)

        scores = eval_result.get("scores", {})
        coverage = (
            eval_result.get("evaluation", {}).get("coverage_analysis")
            or eval_result.get("evaluation", {}).get("coverage_overlap")
            or {}
        )
        summary_rows.append(
            {
                "task_id": task_id,
                "project": project,
                "executability_score": _safe_float(scores.get("executability", 0.0)),
                "line_coverage_overlap": _safe_float(coverage.get("line_overlap_ratio", 0.0)),
                "branch_coverage_overlap": _safe_float(coverage.get("branch_overlap_ratio", 0.0)),
                "coverage_overlap_score": _safe_float(scores.get("coverage_overlap", 0.0)),
                "modification_score": _safe_float(scores.get("modification_score", 0.0)),
                "overall_score": _safe_float(scores.get("overall", 0.0)),
                "status": "success" if eval_result.get("success") else "failed",
                "error": (eval_result.get("error") or ""),
                "result_json": result_json_path,
            }
        )

        batch_results.append(eval_result)
        if eval_result.get("success"):
            successful += 1
        else:
            failed += 1

    summary_csv = os.path.join(output_dir, "evaluation_summary.csv")
    with open(summary_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "task_id",
                "project",
                "executability_score",
                "line_coverage_overlap",
                "branch_coverage_overlap",
                "coverage_overlap_score",
                "modification_score",
                "overall_score",
                "status",
                "error",
                "result_json",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    batch_json = os.path.join(output_dir, "evaluation_batch_results.json")
    with open(batch_json, "w", encoding="utf-8") as f:
        json.dump(
            {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "records_file": records_file,
                    "output_dir": output_dir,
                    "total": len(summary_rows),
                    "successful": successful,
                    "failed": failed,
                },
                "results": batch_results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    return {
        "total": len(summary_rows),
        "successful": successful,
        "failed": failed,
        "summary_csv": summary_csv,
        "batch_json": batch_json,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从worktree_records.csvbatchrunevaluate并导出汇总CSV"
    )
    parser.add_argument(
        "--records",
        "-r",
        default=DEFAULT_RECORDS,
        help="worktree_records.csvpath",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=DEFAULT_OUTPUT_DIR,
        help="evaluateresultoutput directory",
    )
    parser.add_argument(
        "--all-status",
        action="store_true",
        help="default仅evaluatestatus=ready；设置此parameter可evaluate所有状态",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="仅process前N条record（0表示不限制）",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="详细log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Batch Evaluate Worktrees From CSV")
    logger.info(f"records: {args.records}")
    logger.info(f"output : {args.output_dir}")
    logger.info("=" * 60)

    try:
        report = run_batch(
            records_file=args.records,
            output_dir=args.output_dir,
            only_ready=not args.all_status,
            limit=args.limit,
        )

        logger.info("batchevaluatecomplete")
        logger.info(f"  total: {report['total']}")
        logger.info(f"  successful: {report['successful']}")
        logger.info(f"  failed: {report['failed']}")
        logger.info(f"  summary_csv: {report['summary_csv']}")
        logger.info(f"  batch_json: {report['batch_json']}")
        return 0

    except Exception as e:
        logger.error(f"batchevaluateFailed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
