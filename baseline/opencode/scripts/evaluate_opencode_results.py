#!/usr/bin/env python3
"""evaluateOpenCode executionresult
"""

import sys
import os
import json
import argparse
from datetime import datetime
from typing import Dict, List, Any

# baseline/opencode/scripts/evaluate_opencode_results.py -> TUBench/
script_dir = os.path.dirname(os.path.abspath(__file__))  # scripts/
opencode_dir = os.path.dirname(script_dir)  # opencode/
baseline_dir = os.path.dirname(opencode_dir)  # baseline/
project_root = os.path.dirname(baseline_dir)  # TUBench/
sys.path.insert(0, project_root)

from utils.logger import setup_logger, get_logger


class OpenCodeResultEvaluator:
    

    def __init__(self, opencode_results_dir: str, project_base_dir: str):
        """Initialize."""
        self.results_dir = opencode_results_dir
        self.project_base_dir = project_base_dir
        self.logger = get_logger()

    def load_opencode_summary(self) -> Dict[str, Any]:
        
        summary_file = os.path.join(self.results_dir, 'summary.json')
        with open(summary_file, 'r') as f:
            return json.load(f)

    def get_gt_commit_from_worktree_records(self, task_id: int, worktree_records_file: str) -> str:
        
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

        summary = self.load_opencode_summary()
        tasks = []

        for result in summary.get('results', []):
            if not result.get('success'):
                self.logger.warning(f"Task {result['task_id']} failed, skipping")
                continue

            task_id = result['task_id']
            worktree_path = result['worktree_path']

            worktree_name = os.path.basename(worktree_path)
            parts = worktree_name.split('-task_')
            project_name = parts[0]

            # getGT commit
            gt_commit = self.get_gt_commit_from_worktree_records(task_id, worktree_records_file)
            if not gt_commit:
                self.logger.error(f"Failed to get GT commit for task {task_id}")
                continue

            # getprojectpath
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
        """Args:
            worktree_records_file: worktree recordfile
"""
        self.logger.info("Loading OpenCode results...")
        summary = self.load_opencode_summary()

        self.logger.info(f"Found {summary['total']} tasks, {summary['successful']} successful")

        tasks = self.extract_evaluation_tasks(worktree_records_file)
        self.logger.info(f"Extracted {len(tasks)} tasks for evaluation")

        if not tasks:
            self.logger.error("No valid tasks to evaluate")
            return

        from update_evaluation import EvaluationOrchestrator

        project_path = tasks[0]['project']
        orchestrator = EvaluationOrchestrator(project_path)

        self.logger.info("Starting batch evaluation using EvaluationOrchestrator...")

        eval_results = orchestrator.run_batch_evaluation(tasks, output_file)

        self._merge_opencode_info(eval_results, tasks, output_file)

        # outputstatistics
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
        
        # createtask_id
        opencode_info = {t['task_id']: t['opencode_execution'] for t in tasks}

        for result in eval_results['results']:
            task_id = result.get('task_id')
            if task_id in opencode_info:
                result['opencode_execution'] = opencode_info[task_id]

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(eval_results, f, indent=2, ensure_ascii=False)


def parse_args():
    """parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='evaluateOpenCode executionresult - evaluate.pybatchevaluate',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
    Example:
  python baseline/opencode/scripts/evaluate_opencode_results.py \\
    -r /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \\
    -w /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \\
    -p /Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects \\
    -o /Users/mac/Desktop/TestUpdate/TUDataset/evaluation_results.json \\
    --verbose

description:
    '''
    )

    parser.add_argument('--opencode-results', '-r', type=str, required=True,
                        help='OpenCode resultdirectory')
    parser.add_argument('--worktree-records', '-w', type=str, required=True,
                        help='worktree_records.xlsxfile path')
    parser.add_argument('--project-base', '-p', type=str, required=True,
                        help='projectdirectory（）')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='evaluateresultoutput file')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='verbose logging output')

    return parser.parse_args()


def main():
    """main function"""
    args = parse_args()

    # set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("="*60)
    logger.info("OpenCode Results Evaluator (using evaluate.py)")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # createevaluate
        evaluator = OpenCodeResultEvaluator(
            opencode_results_dir=args.opencode_results,
            project_base_dir=args.project_base
        )

        # executeevaluate
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
