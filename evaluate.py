#!/usr/bin/env python3
"""
TUBench Evaluation Tool - main entry point for the evaluation tool
Used to evaluate the effectiveness of outdated test case repair methods
"""

import sys
import os
import json
import argparse
from datetime import datetime

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, AnalysisConfig
from utils.logger import setup_logger, get_logger
from update_evaluation import EvaluationOrchestrator, WorktreeManager


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='TUBench Evaluation Tool - outdated test case repair evaluation tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Prepare a single evaluation task
  python evaluate.py prepare --project /path/to/commons-csv --commit abc123

  # Run evaluation
  python evaluate.py run --worktree /tmp/tubench_eval/commons-csv_abc123_eval

  # Batch evaluation
  python evaluate.py run-batch --input eval_tasks.json --output eval_results.json

  # Clean up worktree
  python evaluate.py cleanup --worktree /tmp/tubench_eval/commons-csv_abc123_eval
  python evaluate.py cleanup --all --project /path/to/commons-csv
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # prepare command
    prepare_parser = subparsers.add_parser('prepare', help='Prepare evaluation environment')
    prepare_parser.add_argument('--project', '-p', type=str, required=True,
                                help='Project path')
    prepare_parser.add_argument('--commit', '-c', type=str, required=True,
                                help='GT commit hash')
    prepare_parser.add_argument('--output-dir', '-o', type=str,
                                help='Worktree output directory')
    prepare_parser.add_argument('--cache-dir', type=str,
                                help='Cache directory (used to read V-0.5 information)')

    # prepare-batch command
    prepare_batch_parser = subparsers.add_parser('prepare-batch', help='Batch prepare evaluation environments')
    prepare_batch_parser.add_argument('--project', '-p', type=str, required=True,
                                      help='Project path')
    prepare_batch_parser.add_argument('--input', '-i', type=str, required=True,
                                      help='Commit list file (JSON format)')
    prepare_batch_parser.add_argument('--output-dir', '-o', type=str,
                                      help='Worktree output directory')

    # run command
    run_parser = subparsers.add_parser('run', help='Run evaluation')
    run_parser.add_argument('--worktree', '-w', type=str, required=True,
                            help='Worktree path')
    run_parser.add_argument('--gt-commit', '-g', type=str, required=True,
                            help='GT commit hash')
    run_parser.add_argument('--output', '-o', type=str,
                            help='Result output file')

    # run-batch command
    run_batch_parser = subparsers.add_parser('run-batch', help='Batch run evaluations')
    run_batch_parser.add_argument('--input', '-i', type=str, required=True,
                                  help='Evaluation task file (JSON format)')
    run_batch_parser.add_argument('--output', '-o', type=str, required=True,
                                  help='Result output file')
    run_batch_parser.add_argument('--project', '-p', type=str,
                                  help='Project path (if not specified in the task file)')

    # report command
    report_parser = subparsers.add_parser('report', help='Generate evaluation report')
    report_parser.add_argument('--input', '-i', type=str, required=True,
                               help='Evaluation result file')
    report_parser.add_argument('--format', '-f', type=str, choices=['json', 'csv'],
                               default='json', help='Output format')

    # cleanup command
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up worktrees')
    cleanup_parser.add_argument('--worktree', '-w', type=str,
                                help='Specify worktree path')
    cleanup_parser.add_argument('--all', action='store_true',
                                help='Clean up all evaluation worktrees')
    cleanup_parser.add_argument('--project', '-p', type=str,
                                help='Project path (used together with --all)')

    # General arguments
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging output')

    return parser.parse_args()


def cmd_prepare(args, logger):
    """Prepare evaluation environment"""
    project_path = os.path.abspath(args.project)

    if not os.path.exists(project_path):
        logger.error(f"Project path does not exist: {project_path}")
        return 1

    # Create WorktreeManager
    eval_dir = args.output_dir or WorktreeManager.DEFAULT_EVAL_DIR
    manager = WorktreeManager(project_path, eval_dir)

    # Prepare worktree
    cache_dir = args.cache_dir or os.path.join(AnalysisConfig.CACHE_DIR, os.path.basename(project_path))
    result = manager.prepare_evaluation_worktree(args.commit, cache_dir)

    if result['success']:
        print(f"\n✓ Created evaluation worktree: {result['worktree_path']}")
        print(f"✓ V-0.5 branch: {result['v05_branch']} ({result['v05_commit'][:8]})")
        print(f"✓ Based on parent: {result['parent_commit'][:8]}")
        print(f"\nPlease modify test code in the following directory:")
        print(f"  {result['worktree_path']}")
        print(f"\nAfter modification, run:")
        print(f"  python evaluate.py run --worktree {result['worktree_path']} --gt-commit {args.commit}")
        return 0
    else:
        logger.error(f"Preparation failed: {result.get('error')}")
        return 1


def cmd_prepare_batch(args, logger):
    """Batch prepare evaluation environments"""
    project_path = os.path.abspath(args.project)

    if not os.path.exists(project_path):
        logger.error(f"Project path does not exist: {project_path}")
        return 1

    # Read commit list
    with open(args.input, 'r') as f:
        data = json.load(f)

    commits = data.get('commits', data) if isinstance(data, dict) else data

    eval_dir = args.output_dir or WorktreeManager.DEFAULT_EVAL_DIR
    manager = WorktreeManager(project_path, eval_dir)
    cache_dir = os.path.join(AnalysisConfig.CACHE_DIR, os.path.basename(project_path))

    results = []
    for i, commit in enumerate(commits):
        commit_hash = commit if isinstance(commit, str) else commit.get('commit')
        logger.info(f"[{i+1}/{len(commits)}] Preparing {commit_hash[:8]}...")

        result = manager.prepare_evaluation_worktree(commit_hash, cache_dir)
        results.append({
            'commit': commit_hash,
            'success': result['success'],
            'worktree_path': result.get('worktree_path'),
            'error': result.get('error')
        })

    # Output results
    successful = sum(1 for r in results if r['success'])
    print(f"\nPreparation complete: {successful}/{len(commits)} succeeded")

    # Save task file
    tasks_file = os.path.join(eval_dir, 'eval_tasks.json')
    tasks = {
        'tasks': [
            {
                'project': project_path,
                'gt_commit': r['commit'],
                'user_worktree': r['worktree_path']
            }
            for r in results if r['success']
        ]
    }
    with open(tasks_file, 'w') as f:
        json.dump(tasks, f, indent=2)
    print(f"Task file saved: {tasks_file}")

    return 0


def cmd_run(args, logger):
    """Run evaluation"""
    worktree_path = os.path.abspath(args.worktree)
    gt_commit = args.gt_commit

    if not os.path.exists(worktree_path):
        logger.error(f"Worktree path does not exist: {worktree_path}")
        return 1

    # Get project path (retrieve original repository path from worktree's git config)
    from git import Repo
    worktree_repo = Repo(worktree_path)
    git_common_dir = worktree_repo.git.rev_parse('--git-common-dir')
    project_path = os.path.dirname(git_common_dir)

    # Create evaluator
    orchestrator = EvaluationOrchestrator(project_path)

    # Run evaluation
    logger.info("Starting evaluation...")
    result = orchestrator.run_evaluation(worktree_path, gt_commit)

    # Output results
    print("\n" + "=" * 60)
    print("Evaluation Results")
    print("=" * 60)

    if result['success']:
        print(f"✓ Evaluation succeeded")
        print(f"\nGT Commit: {result['gt_commit'][:8]}")
        print(f"V-0.5 Commit: {result.get('v05_commit', 'N/A')[:8] if result.get('v05_commit') else 'N/A'}")

        exec_result = result['evaluation']['executability']
        print(f"\n[Executability]")
        print(f"  Compile: {'✓ succeeded' if exec_result.get('compile_success') else '✗ failed'}")
        print(f"  Test: {'✓ succeeded' if exec_result.get('test_success') else '✗ failed'}")
        if exec_result.get('test_results'):
            tr = exec_result['test_results']
            print(f"  Test statistics: {tr.get('passed', 0)} passed, {tr.get('failed', 0)} failed, {tr.get('errors', 0)} errors")

        cov_result = result['evaluation']['coverage_overlap']
        print(f"\n[Coverage Increment Overlap]")
        print(f"  Line coverage overlap: {cov_result.get('line_overlap_ratio', 0):.2%}")
        print(f"  Branch coverage overlap: {cov_result.get('branch_overlap_ratio', 0):.2%}")
        print(f"  GT increment lines: {cov_result.get('gt_increment_lines', 0)}")
        print(f"  User increment lines: {cov_result.get('user_increment_lines', 0)}")

        effort_result = result['evaluation']['modification_effort']
        print(f"\n[Modification Effort]")
        print(f"  Number of test methods modified: {effort_result.get('total_methods', 0)}")
        print(f"  Modification effort score: {effort_result.get('average_score', 0):.2%} (higher is better, meaning fewer changes)")

        # Overall score
        scores = result.get('scores', {})
        print(f"\n[Overall Score]")
        print(f"  Coverage increment overlap: {scores.get('coverage_overlap', 0):.2%}")
        print(f"  Modification effort score: {scores.get('modification_score', 0):.2%}")
        print(f"  Final score: {scores.get('overall', 0):.2%} (0.6×coverage + 0.4×effort)")

    else:
        print(f"✗ Evaluation failed: {result.get('error')}")

    # Save results
    if args.output:
        output_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        # Convert set to list
        def convert_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            elif isinstance(obj, dict):
                return {k: convert_sets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_sets(item) for item in obj]
            return obj

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(convert_sets(result), f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {output_path}")

    return 0 if result['success'] else 1


def cmd_run_batch(args, logger):
    """Batch run evaluations"""
    # Read task file
    with open(args.input, 'r') as f:
        data = json.load(f)

    tasks = data.get('tasks', [])
    if not tasks:
        logger.error("No tasks found in the task file")
        return 1

    # Get project path
    project_path = args.project
    if not project_path:
        # Get from the first task
        project_path = tasks[0].get('project')

    if not project_path or not os.path.exists(project_path):
        logger.error("Cannot determine project path")
        return 1

    # Create evaluator
    orchestrator = EvaluationOrchestrator(project_path)

    # Run batch evaluation
    results = orchestrator.run_batch_evaluation(tasks, args.output)

    # Output statistics
    print("\n" + "=" * 60)
    print("Batch Evaluation Complete")
    print("=" * 60)
    print(f"Total tasks: {results['metadata']['total_tasks']}")
    print(f"Succeeded: {results['metadata']['successful']}")
    print(f"Failed: {results['metadata']['failed']}")
    print(f"\nResults saved to: {args.output}")

    return 0


def cmd_report(args, logger):
    """Generate evaluation report"""
    with open(args.input, 'r') as f:
        data = json.load(f)

    results = data.get('results', [])

    print("\n" + "=" * 60)
    print("Evaluation Report")
    print("=" * 60)

    if data.get('metadata'):
        meta = data['metadata']
        print(f"Evaluation time: {meta.get('evaluation_time')}")
        print(f"Total tasks: {meta.get('total_tasks')}")
        print(f"Succeeded: {meta.get('successful')}")
        print(f"Failed: {meta.get('failed')}")

    print("\nDetailed results:")
    print("-" * 60)

    for r in results:
        status = r.get('status', 'unknown')
        gt_commit = r.get('gt_commit', 'unknown')[:8]

        if status == 'success':
            exec_result = r.get('evaluation', {}).get('executability', {})
            cov_result = r.get('evaluation', {}).get('coverage_overlap', {})
            effort_result = r.get('evaluation', {}).get('modification_effort', {})

            compile_ok = '✓' if exec_result.get('compile_success') else '✗'
            test_ok = '✓' if exec_result.get('test_success') else '✗'
            line_overlap = cov_result.get('line_overlap_ratio', 0)
            # New field is average_score; retain compatibility with old field average_jaccard
            jaccard = effort_result.get('average_score', effort_result.get('average_jaccard', 0))

            print(f"{gt_commit}: compile{compile_ok} test{test_ok} "
                  f"coverage_overlap={line_overlap:.0%} Jaccard={jaccard:.0%}")
        else:
            error = r.get('error', 'Unknown error')[:50]
            print(f"{gt_commit}: ✗ {error}")

    return 0


def cmd_cleanup(args, logger):
    """Clean up worktrees"""
    if args.all:
        if not args.project:
            logger.error("--project must be specified when using --all")
            return 1

        manager = WorktreeManager(args.project)
        count = manager.cleanup_all_worktrees()
        print(f"Cleaned up {count} evaluation worktrees")

    elif args.worktree:
        # Get project path
        from git import Repo
        worktree_repo = Repo(args.worktree)
        git_common_dir = worktree_repo.git.rev_parse('--git-common-dir')
        project_path = os.path.dirname(git_common_dir)

        manager = WorktreeManager(project_path)
        if manager.cleanup_worktree(args.worktree):
            print(f"Cleaned up: {args.worktree}")
        else:
            logger.error("Cleanup failed")
            return 1

    else:
        logger.error("Please specify --worktree or --all")
        return 1

    return 0


def main():
    """Main function"""
    args = parse_args()

    # Set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    if not args.command:
        print("Please specify a command. Use --help to view help.")
        return 1

    # Execute command
    commands = {
        'prepare': cmd_prepare,
        'prepare-batch': cmd_prepare_batch,
        'run': cmd_run,
        'run-batch': cmd_run_batch,
        'report': cmd_report,
        'cleanup': cmd_cleanup
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        return cmd_func(args, logger)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
