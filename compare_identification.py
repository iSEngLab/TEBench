#!/usr/bin/env python3
"""
Identification Result Comparison Tool
Compares results from an identification method against Ground Truth and calculates Precision, Recall, F1, and other metrics
"""

import sys
import os
import json
import argparse
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger, get_logger


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Identification Result Comparison Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Compare identification results with GT
  python compare_identification.py \\
    --gt identify_evaluation/gt_changes_all.json \\
    --predicted method_results.json \\
    --output comparison_results.json

  # Compare only a specific project
  python compare_identification.py \\
    --gt identify_evaluation/gt_changes_all.json \\
    --predicted method_results.json \\
    --output comparison_results.json \\
    --project commons-csv
        '''
    )

    parser.add_argument('--gt', '-g', type=str, required=True,
                        help='Ground Truth file path')
    parser.add_argument('--predicted', '-p', type=str, required=True,
                        help='Identification method result file path')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='Output comparison result file path')
    parser.add_argument('--project', type=str,
                        help='Compare only the specified project')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging output')

    return parser.parse_args()


def load_gt_data(gt_file: str) -> Dict:
    """Load Ground Truth data"""
    with open(gt_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_predicted_data(predicted_file: str) -> Dict:
    """
    Load identification method result data

    Expected format:
    {
      "results": [
        {
          "task_id": 1,
          "project": "commons-csv",
          "identified_tests": [
            {
              "file_path": "src/test/java/.../Test.java",
              "methods": ["testMethod1", "testMethod2"]
            }
          ]
        }
      ]
    }
    """
    with open(predicted_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_gt_obsolete_tests(task_data: Dict) -> Set[Tuple[str, str]]:
    """
    Extract outdated test methods from GT data

    Outdated test definition: test methods that have been modified or deleted

    Returns:
        Set of (file_path, method_name) tuples
    """
    obsolete_tests = set()

    if not task_data.get('test_changes'):
        return obsolete_tests

    test_changes = task_data['test_changes']

    # Modified and deleted methods in modified files
    for file_info in test_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # Modified methods
        for method in file_info.get('modified_methods', []):
            obsolete_tests.add((file_path, method))

        # Deleted methods
        for method in file_info.get('deleted_methods', []):
            obsolete_tests.add((file_path, method))

    # All methods in deleted files
    for file_info in test_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            obsolete_tests.add((file_path, method))

    return obsolete_tests


def extract_predicted_tests(task_data: Dict) -> Set[Tuple[str, str]]:
    """
    Extract identified test methods from identification results

    Returns:
        Set of (file_path, method_name) tuples
    """
    predicted_tests = set()

    for file_info in task_data.get('identified_tests', []):
        file_path = file_info['file_path']
        for method in file_info.get('methods', []):
            predicted_tests.add((file_path, method))

    return predicted_tests


def calculate_metrics(gt_tests: Set, predicted_tests: Set) -> Dict:
    """
    Calculate evaluation metrics

    Args:
        gt_tests: Set of outdated tests from Ground Truth
        predicted_tests: Set of tests identified by the identification method

    Returns:
        Dictionary containing Precision, Recall, F1, and other metrics
    """
    # True Positives: correctly identified outdated tests
    tp = len(gt_tests & predicted_tests)

    # False Positives: incorrectly identified (not actually outdated but identified as outdated)
    fp = len(predicted_tests - gt_tests)

    # False Negatives: missed outdated tests
    fn = len(gt_tests - predicted_tests)

    # True Negatives: cannot be directly calculated (requires knowing all non-outdated tests)

    # Precision: proportion of identified tests that are truly outdated
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Recall: proportion of all outdated tests that were identified
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    # F1 Score: harmonic mean of Precision and Recall
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        'true_positives': tp,
        'false_positives': fp,
        'false_negatives': fn,
        'precision': precision,
        'recall': recall,
        'f1_score': f1,
        'gt_total': len(gt_tests),
        'predicted_total': len(predicted_tests)
    }


def compare_tasks(gt_data: Dict, predicted_data: Dict, project_filter: str = None) -> Dict:
    """
    Compare identification results for all tasks

    Args:
        gt_data: Ground Truth data
        predicted_data: Identification method result data
        project_filter: Project filter

    Returns:
        Dictionary of comparison results
    """
    logger = get_logger()

    # Build index of predicted data
    predicted_index = {}
    for task in predicted_data.get('results', []):
        key = (task['task_id'], task['project'])
        predicted_index[key] = task

    task_results = []

    for gt_task in gt_data.get('results', []):
        task_id = gt_task['task_id']
        project = gt_task['project']

        # Project filter
        if project_filter and project != project_filter:
            continue

        logger.info(f"Comparing task {task_id} ({project})")

        # Extract outdated tests from GT
        gt_tests = extract_gt_obsolete_tests(gt_task)

        # Find the corresponding predicted data
        key = (task_id, project)
        predicted_task = predicted_index.get(key)

        if not predicted_task:
            logger.warning(f"  Identification result for task {task_id} not found")
            predicted_tests = set()
        else:
            predicted_tests = extract_predicted_tests(predicted_task)

        # Calculate metrics
        metrics = calculate_metrics(gt_tests, predicted_tests)

        logger.info(f"  GT outdated tests: {metrics['gt_total']}, "
                   f"Identified: {metrics['predicted_total']}, "
                   f"Correct: {metrics['true_positives']}")
        logger.info(f"  Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

        task_results.append({
            'task_id': task_id,
            'project': project,
            'type': gt_task.get('type'),
            'metrics': metrics,
            'details': {
                'gt_tests': sorted(list(gt_tests)),
                'predicted_tests': sorted(list(predicted_tests)),
                'true_positives': sorted(list(gt_tests & predicted_tests)),
                'false_positives': sorted(list(predicted_tests - gt_tests)),
                'false_negatives': sorted(list(gt_tests - predicted_tests))
            }
        })

    return task_results


def aggregate_metrics(task_results: List[Dict]) -> Dict:
    """
    Aggregate metrics across all tasks

    Args:
        task_results: List of task results

    Returns:
        Aggregated metrics
    """
    total_tp = sum(r['metrics']['true_positives'] for r in task_results)
    total_fp = sum(r['metrics']['false_positives'] for r in task_results)
    total_fn = sum(r['metrics']['false_negatives'] for r in task_results)
    total_gt = sum(r['metrics']['gt_total'] for r in task_results)
    total_predicted = sum(r['metrics']['predicted_total'] for r in task_results)

    # Macro Average: average of metrics per task
    macro_precision = sum(r['metrics']['precision'] for r in task_results) / len(task_results) if task_results else 0
    macro_recall = sum(r['metrics']['recall'] for r in task_results) / len(task_results) if task_results else 0
    macro_f1 = sum(r['metrics']['f1_score'] for r in task_results) / len(task_results) if task_results else 0

    # Micro Average: calculated from total TP/FP/FN across all tasks
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if (micro_precision + micro_recall) > 0 else 0

    # Statistics by project
    by_project = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'gt': 0, 'pred': 0, 'count': 0})
    for r in task_results:
        project = r['project']
        by_project[project]['tp'] += r['metrics']['true_positives']
        by_project[project]['fp'] += r['metrics']['false_positives']
        by_project[project]['fn'] += r['metrics']['false_negatives']
        by_project[project]['gt'] += r['metrics']['gt_total']
        by_project[project]['pred'] += r['metrics']['predicted_total']
        by_project[project]['count'] += 1

    # Calculate metrics for each project
    project_metrics = {}
    for project, stats in by_project.items():
        precision = stats['tp'] / (stats['tp'] + stats['fp']) if (stats['tp'] + stats['fp']) > 0 else 0
        recall = stats['tp'] / (stats['tp'] + stats['fn']) if (stats['tp'] + stats['fn']) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        project_metrics[project] = {
            'tasks': stats['count'],
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'true_positives': stats['tp'],
            'false_positives': stats['fp'],
            'false_negatives': stats['fn'],
            'gt_total': stats['gt'],
            'predicted_total': stats['pred']
        }

    # Statistics by type
    by_type = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'gt': 0, 'pred': 0, 'count': 0})
    for r in task_results:
        task_type = r.get('type', 'unknown')
        by_type[task_type]['tp'] += r['metrics']['true_positives']
        by_type[task_type]['fp'] += r['metrics']['false_positives']
        by_type[task_type]['fn'] += r['metrics']['false_negatives']
        by_type[task_type]['gt'] += r['metrics']['gt_total']
        by_type[task_type]['pred'] += r['metrics']['predicted_total']
        by_type[task_type]['count'] += 1

    type_metrics = {}
    for task_type, stats in by_type.items():
        precision = stats['tp'] / (stats['tp'] + stats['fp']) if (stats['tp'] + stats['fp']) > 0 else 0
        recall = stats['tp'] / (stats['tp'] + stats['fn']) if (stats['tp'] + stats['fn']) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        type_metrics[task_type] = {
            'tasks': stats['count'],
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'true_positives': stats['tp'],
            'false_positives': stats['fp'],
            'false_negatives': stats['fn'],
            'gt_total': stats['gt'],
            'predicted_total': stats['pred']
        }

    return {
        'overall': {
            'total_tasks': len(task_results),
            'total_true_positives': total_tp,
            'total_false_positives': total_fp,
            'total_false_negatives': total_fn,
            'total_gt_obsolete_tests': total_gt,
            'total_predicted_tests': total_predicted,
            'macro_precision': macro_precision,
            'macro_recall': macro_recall,
            'macro_f1': macro_f1,
            'micro_precision': micro_precision,
            'micro_recall': micro_recall,
            'micro_f1': micro_f1
        },
        'by_project': project_metrics,
        'by_type': type_metrics
    }


def main():
    """Main function"""
    args = parse_args()

    # Set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Identification Result Comparison Tool")
    logger.info("=" * 60)

    # Load data
    logger.info(f"Loading Ground Truth: {args.gt}")
    gt_data = load_gt_data(args.gt)

    logger.info(f"Loading identification results: {args.predicted}")
    predicted_data = load_predicted_data(args.predicted)

    # Compare tasks
    logger.info("\nStarting comparison...")
    task_results = compare_tasks(gt_data, predicted_data, args.project)

    # Aggregate metrics
    logger.info("\nCalculating aggregated metrics...")
    aggregated = aggregate_metrics(task_results)

    # Save results
    output_data = {
        'metadata': {
            'gt_file': args.gt,
            'predicted_file': args.predicted,
            'project_filter': args.project
        },
        'aggregated_metrics': aggregated,
        'task_results': task_results
    }

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Output results
    logger.info("\n" + "=" * 60)
    logger.info("Comparison complete")
    logger.info("=" * 60)

    overall = aggregated['overall']
    logger.info(f"\nOverall metrics (total {overall['total_tasks']} tasks):")
    logger.info(f"  Total GT outdated tests: {overall['total_gt_obsolete_tests']}")
    logger.info(f"  Total identified tests: {overall['total_predicted_tests']}")
    logger.info(f"  Correctly identified (TP): {overall['total_true_positives']}")
    logger.info(f"  Incorrectly identified (FP): {overall['total_false_positives']}")
    logger.info(f"  Missed (FN): {overall['total_false_negatives']}")

    logger.info(f"\nMacro Average:")
    logger.info(f"  Precision: {overall['macro_precision']:.2%}")
    logger.info(f"  Recall: {overall['macro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['macro_f1']:.2%}")

    logger.info(f"\nMicro Average:")
    logger.info(f"  Precision: {overall['micro_precision']:.2%}")
    logger.info(f"  Recall: {overall['micro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['micro_f1']:.2%}")

    logger.info(f"\nStatistics by project:")
    for project, metrics in aggregated['by_project'].items():
        logger.info(f"  {project} ({metrics['tasks']} tasks):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\nStatistics by type:")
    for task_type, metrics in aggregated['by_type'].items():
        logger.info(f"  {task_type} ({metrics['tasks']} tasks):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\nDetailed results saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
