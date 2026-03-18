#!/usr/bin/env python3
"""
测试单个任务的评估 - 用于调试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger, get_logger
from evaluation import EvaluationOrchestrator

setup_logger(level='DEBUG')
logger = get_logger()

# 测试第2个任务（task 1失败了）
project_path = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects/commons-csv"
worktree_path = "/Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_002_eval"
gt_commit = "030fb8e3"  # 需要从 worktree_records.xlsx 获取

logger.info(f"Testing evaluation on task 2")
logger.info(f"Project: {project_path}")
logger.info(f"Worktree: {worktree_path}")
logger.info(f"GT Commit: {gt_commit}")

orchestrator = EvaluationOrchestrator(project_path)

try:
    result = orchestrator.run_evaluation(worktree_path, gt_commit)

    logger.info("\n" + "="*60)
    logger.info("Evaluation Result")
    logger.info("="*60)

    if result['success']:
        logger.info("✓ Evaluation successful")

        exec_result = result['evaluation']['executability']
        logger.info(f"\n[Executability]")
        logger.info(f"  Compile: {'✓' if exec_result.get('compile_success') else '✗'}")
        logger.info(f"  Test: {'✓' if exec_result.get('test_success') else '✗'}")

        cov_result = result['evaluation']['coverage_overlap']
        logger.info(f"\n[Coverage Overlap]")
        logger.info(f"  Line overlap: {cov_result.get('line_overlap_ratio', 0):.2%}")
        logger.info(f"  Branch overlap: {cov_result.get('branch_overlap_ratio', 0):.2%}")

        effort_result = result['evaluation']['modification_effort']
        logger.info(f"\n[Modification Effort]")
        logger.info(f"  Total methods: {effort_result.get('total_methods', 0)}")
        logger.info(f"  Average score: {effort_result.get('average_score', 0):.2%}")

        scores = result.get('scores', {})
        logger.info(f"\n[Overall Score]")
        logger.info(f"  Final score: {scores.get('overall', 0):.2%}")
    else:
        logger.error(f"✗ Evaluation failed: {result.get('error')}")

except Exception as e:
    logger.error(f"Exception during evaluation: {e}", exc_info=True)
