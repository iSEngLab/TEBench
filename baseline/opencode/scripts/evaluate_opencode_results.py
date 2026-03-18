#!/usr/bin/env python3
"""
评估OpenCode执行结果
从OpenCode的输出结果中提取任务信息，并使用evaluate.py的批量评估功能进行评估
"""

import sys
import os
import json
import argparse
from datetime import datetime
from typing import Dict, List, Any

# 添加项目根目录到路径
# baseline/opencode/scripts/evaluate_opencode_results.py -> TUBench/
script_dir = os.path.dirname(os.path.abspath(__file__))  # scripts/
opencode_dir = os.path.dirname(script_dir)  # opencode/
baseline_dir = os.path.dirname(opencode_dir)  # baseline/
project_root = os.path.dirname(baseline_dir)  # TUBench/
sys.path.insert(0, project_root)

from utils.logger import setup_logger, get_logger


class OpenCodeResultEvaluator:
    """OpenCode结果评估器 - 将OpenCode结果转换为evaluate.py的输入格式"""

    def __init__(self, opencode_results_dir: str, project_base_dir: str):
        """
        初始化

        Args:
            opencode_results_dir: OpenCode结果目录
            project_base_dir: 项目基础目录（包含原始仓库）
        """
        self.results_dir = opencode_results_dir
        self.project_base_dir = project_base_dir
        self.logger = get_logger()

    def load_opencode_summary(self) -> Dict[str, Any]:
        """加载OpenCode执行汇总"""
        summary_file = os.path.join(self.results_dir, 'summary.json')
        with open(summary_file, 'r') as f:
            return json.load(f)

    def get_gt_commit_from_worktree_records(self, task_id: int, worktree_records_file: str) -> str:
        """从worktree_records.xlsx获取GT commit"""
        try:
            import pandas as pd
            df = pd.read_excel(worktree_records_file)
            row = df[df['task_id'] == task_id]
            if len(row) > 0:
                return row.iloc[0]['v_0_commit']
        except Exception as e:
            self.logger.error(f"Failed to get GT commit for task {task_id}: {e}")
        return None

    def extract_evaluation_tasks(self, worktree_records_file: str) -> List[Dict[str, Any]]:
        """
        从OpenCode结果中提取评估任务，转换为evaluate.py的输入格式

        Returns:
            list: 评估任务列表，格式与evaluate.py run-batch兼容
        """
        summary = self.load_opencode_summary()
        tasks = []

        for result in summary.get('results', []):
            if not result.get('success'):
                self.logger.warning(f"Task {result['task_id']} failed, skipping")
                continue

            task_id = result['task_id']
            worktree_path = result['worktree_path']

            # 从worktree路径提取项目名
            worktree_name = os.path.basename(worktree_path)
            parts = worktree_name.split('-task_')
            project_name = parts[0]

            # 获取GT commit
            gt_commit = self.get_gt_commit_from_worktree_records(task_id, worktree_records_file)
            if not gt_commit:
                self.logger.error(f"Failed to get GT commit for task {task_id}")
                continue

            # 获取项目路径
            project_path = os.path.join(self.project_base_dir, project_name)
            if not os.path.exists(project_path):
                self.logger.error(f"Project path not found: {project_path}")
                continue

            tasks.append({
                'task_id': task_id,
                'project': project_path,
                'gt_commit': gt_commit,
                'user_worktree': worktree_path,
                'opencode_execution': {
                    'duration': result.get('duration'),
                    'modified_files': result.get('modified_files', []),
                }
            })

        return tasks

    def evaluate_all(self, worktree_records_file: str, output_file: str):
        """
        评估所有任务 - 使用evaluate.py的批量评估功能

        Args:
            worktree_records_file: worktree记录文件
            output_file: 输出文件
        """
        self.logger.info("Loading OpenCode results...")
        summary = self.load_opencode_summary()

        self.logger.info(f"Found {summary['total']} tasks, {summary['successful']} successful")

        # 提取评估任务
        tasks = self.extract_evaluation_tasks(worktree_records_file)
        self.logger.info(f"Extracted {len(tasks)} tasks for evaluation")

        if not tasks:
            self.logger.error("No valid tasks to evaluate")
            return

        # 使用evaluate.py的批量评估功能
        # 直接调用EvaluationOrchestrator
        from evaluation import EvaluationOrchestrator

        # 使用第一个任务的项目路径创建orchestrator
        project_path = tasks[0]['project']
        orchestrator = EvaluationOrchestrator(project_path)

        self.logger.info("Starting batch evaluation using EvaluationOrchestrator...")

        # 调用批量评估
        eval_results = orchestrator.run_batch_evaluation(tasks, output_file)

        # 合并OpenCode执行信息到评估结果
        self._merge_opencode_info(eval_results, tasks, output_file)

        # 输出统计
        meta = eval_results['metadata']
        self.logger.info(f"\nEvaluation complete!")
        self.logger.info(f"  Total: {meta['total_tasks']}")
        self.logger.info(f"  Successful: {meta['successful']}")
        self.logger.info(f"  Failed: {meta['failed']}")

        if meta.get('average_scores'):
            scores = meta['average_scores']
            self.logger.info(f"\nAverage Scores:")
            self.logger.info(f"  Coverage Overlap: {scores.get('avg_coverage_overlap', 0):.2%}")
            self.logger.info(f"  Modification Score: {scores.get('avg_modification_score', 0):.2%}")
            self.logger.info(f"  Overall Score: {scores.get('avg_overall_score', 0):.2%}")
            self.logger.info(f"  Compile Success Rate: {scores.get('compile_success_rate', 0):.2%}")
            self.logger.info(f"  Test Success Rate: {scores.get('test_success_rate', 0):.2%}")

        self.logger.info(f"\nResults saved to: {output_file}")

    def _merge_opencode_info(self, eval_results: Dict, tasks: List[Dict], output_file: str):
        """将OpenCode执行信息合并到评估结果中"""
        # 创建task_id到OpenCode信息的映射
        opencode_info = {t['task_id']: t['opencode_execution'] for t in tasks}

        # 合并信息
        for result in eval_results['results']:
            task_id = result.get('task_id')
            if task_id in opencode_info:
                result['opencode_execution'] = opencode_info[task_id]

        # 重新保存
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(eval_results, f, indent=2, ensure_ascii=False)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='评估OpenCode执行结果 - 使用evaluate.py的批量评估功能',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python baseline/opencode/scripts/evaluate_opencode_results.py \\
    -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \\
    -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \\
    -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \\
    -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \\
    --verbose

说明:
  本脚本是evaluate.py的包装器，用于：
  1. 从OpenCode结果目录读取执行信息
  2. 从worktree_records.xlsx提取GT commit
  3. 调用evaluate.py的批量评估功能
  4. 合并OpenCode执行信息和评估结果

  评估逻辑完全使用evaluate.py中的EvaluationOrchestrator，确保一致性。
        '''
    )

    parser.add_argument('--opencode-results', '-r', type=str, required=True,
                        help='OpenCode结果目录')
    parser.add_argument('--worktree-records', '-w', type=str, required=True,
                        help='worktree_records.xlsx文件路径')
    parser.add_argument('--project-base', '-p', type=str, required=True,
                        help='项目基础目录（包含原始仓库）')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='评估结果输出文件')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("="*60)
    logger.info("OpenCode Results Evaluator (using evaluate.py)")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # 创建评估器
        evaluator = OpenCodeResultEvaluator(
            opencode_results_dir=args.opencode_results,
            project_base_dir=args.project_base
        )

        # 执行评估
        evaluator.evaluate_all(
            worktree_records_file=args.worktree_records,
            output_file=args.output
        )

        return 0

    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
