#!/usr/bin/env python3
"""
Ground Truth Test Change Extraction Tool
Reads task information from worktree_records.csv and extracts GT test changes for each task
"""

import sys
import os
import csv
import json
import argparse
from datetime import datetime
from typing import List, Dict

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from identify_evaluation import GTTestChangeExtractor
from utils.logger import setup_logger, get_logger


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Ground Truth Test Change Extraction Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Extract GT changes from CSV file
  python extract_gt_changes.py --input /path/to/worktree_records.csv --output gt_changes.json

  # Process only a specific project
  python extract_gt_changes.py --input records.csv --output gt_changes.json --project commons-csv

  # Process only a specific task ID range
  python extract_gt_changes.py --input records.csv --output gt_changes.json --task-range 1-10
        '''
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='Input CSV file path (worktree_records.csv)')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='Output JSON file path')
    parser.add_argument('--project', '-p', type=str, nargs='+',
                        help='Process only specified projects (e.g. commons-csv), supports multiple projects')
    parser.add_argument('--task-range', '-r', type=str,
                        help='Task ID range (e.g. 1-10)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging output')

    return parser.parse_args()


def read_worktree_records(csv_path: str) -> List[Dict]:
    """
    Read worktree_records.csv file

    Args:
        csv_path: CSV file path

    Returns:
        List of task records
    """
    records = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)

    return records


def filter_records(records: List[Dict], project: List[str] = None, task_range: str = None) -> List[Dict]:
    """
    Filter task records

    Args:
        records: All records
        project: Project name list filter
        task_range: Task ID range (e.g. "1-10")

    Returns:
        Filtered records
    """
    filtered = records

    # Filter by project
    if project:
        filtered = [r for r in filtered if r['project'] in project]

    # Filter by task ID range
    if task_range:
        try:
            start, end = map(int, task_range.split('-'))
            filtered = [r for r in filtered if start <= int(r['task_id']) <= end]
        except ValueError:
            print(f"Warning: Invalid task range format: {task_range}")

    return filtered


def extract_all_gt_changes(records: List[Dict], logger) -> List[Dict]:
    """
    Extract GT changes for all tasks

    Args:
        records: List of task records
        logger: Logger

    Returns:
        List of GT change information
    """
    results = []
    current_project = None
    extractor = None

    for i, record in enumerate(records):
        task_id = record['task_id']
        project = record['project']
        project_path = record['project_path']
        v_minus_1 = record['v_minus_1_commit']
        v_0 = record['v_0_commit']
        task_type = record['type']

        logger.info(f"[{i+1}/{len(records)}] Processing task {task_id} ({project}): {v_0[:8]}")

        # Check if project path exists
        if not os.path.exists(project_path):
            logger.warning(f"  Project path does not exist: {project_path}")
            results.append({
                'task_id': int(task_id),
                'project': project,
                'v_minus_1_commit': v_minus_1,
                'v_0_commit': v_0,
                'type': task_type,
                'error': 'Project path not found',
                'test_changes': None
            })
            continue

        # If the project changed, create a new extractor
        if project != current_project:
            current_project = project
            extractor = GTTestChangeExtractor(project_path)
            logger.info(f"  Switching to project: {project}")

        try:
            # Extract test changes
            test_changes = extractor.extract_test_changes(v_minus_1, v_0)

            result = {
                'task_id': int(task_id),
                'project': project,
                'v_minus_1_commit': v_minus_1,
                'v_0_commit': v_0,
                'type': task_type,
                'test_changes': test_changes
            }

            # Output summary
            summary = test_changes['summary']
            logger.info(f"  ✓ Methods: +{summary['total_test_methods_added']} "
                       f"~{summary['total_test_methods_modified']} "
                       f"-{summary['total_test_methods_deleted']}")
            logger.info(f"  ✓ Files: +{summary['total_test_files_added']} "
                       f"~{summary['total_test_files_modified']} "
                       f"-{summary['total_test_files_deleted']}")

            results.append(result)

        except Exception as e:
            logger.error(f"  ✗ Extraction failed: {str(e)}")
            results.append({
                'task_id': int(task_id),
                'project': project,
                'v_minus_1_commit': v_minus_1,
                'v_0_commit': v_0,
                'type': task_type,
                'error': str(e),
                'test_changes': None
            })

    return results


def generate_statistics(results: List[Dict]) -> Dict:
    """
    Generate statistics

    Args:
        results: List of GT change results

    Returns:
        Statistics dictionary
    """
    total_tasks = len(results)
    successful = sum(1 for r in results if 'error' not in r)
    failed = total_tasks - successful

    # Statistics by project
    projects = {}
    for r in results:
        project = r['project']
        if project not in projects:
            projects[project] = {'total': 0, 'successful': 0}
        projects[project]['total'] += 1
        if 'error' not in r:
            projects[project]['successful'] += 1

    # Statistics by type
    types = {}
    for r in results:
        task_type = r['type']
        if task_type not in types:
            types[task_type] = {'total': 0, 'successful': 0}
        types[task_type]['total'] += 1
        if 'error' not in r:
            types[task_type]['successful'] += 1

    # Change statistics
    total_methods_added = 0
    total_methods_modified = 0
    total_methods_deleted = 0
    total_files_modified = 0
    total_files_added = 0
    total_files_deleted = 0

    for r in results:
        if 'error' not in r and r['test_changes']:
            summary = r['test_changes']['summary']
            total_methods_added += summary['total_test_methods_added']
            total_methods_modified += summary['total_test_methods_modified']
            total_methods_deleted += summary['total_test_methods_deleted']
            total_files_modified += summary['total_test_files_modified']
            total_files_added += summary['total_test_files_added']
            total_files_deleted += summary['total_test_files_deleted']

    return {
        'total_tasks': total_tasks,
        'successful': successful,
        'failed': failed,
        'by_project': projects,
        'by_type': types,
        'total_changes': {
            'methods_added': total_methods_added,
            'methods_modified': total_methods_modified,
            'methods_deleted': total_methods_deleted,
            'files_modified': total_files_modified,
            'files_added': total_files_added,
            'files_deleted': total_files_deleted
        }
    }


def main():
    """Main function"""
    args = parse_args()

    # Set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Ground Truth Test Change Extraction Tool")
    logger.info("=" * 60)

    # Read CSV file
    logger.info(f"Reading CSV file: {args.input}")
    records = read_worktree_records(args.input)
    logger.info(f"Read {len(records)} records in total")

    # Filter records
    filtered_records = filter_records(records, args.project, args.task_range)
    logger.info(f"{len(filtered_records)} records remaining after filtering")

    if not filtered_records:
        logger.error("No records match the criteria")
        return 1

    # Extract GT changes
    logger.info("\nStarting GT change extraction...")
    results = extract_all_gt_changes(filtered_records, logger)

    # Generate statistics
    statistics = generate_statistics(results)

    # save results
    output_data = {
        'metadata': {
            'extraction_time': datetime.now().isoformat(),
            'input_file': args.input,
            'total_tasks': len(results),
            'successful': statistics['successful'],
            'failed': statistics['failed']
        },
        'statistics': statistics,
        'results': results
    }

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Output statistics
    logger.info("\n" + "=" * 60)
    logger.info("Extraction complete")
    logger.info("=" * 60)
    logger.info(f"Total tasks: {statistics['total_tasks']}")
    logger.info(f"Succeeded: {statistics['successful']}")
    logger.info(f"Failed: {statistics['failed']}")

    logger.info("\nStatistics by project:")
    for project, stats in statistics['by_project'].items():
        logger.info(f"  {project}: {stats['successful']}/{stats['total']}")

    logger.info("\nStatistics by type:")
    for task_type, stats in statistics['by_type'].items():
        logger.info(f"  {task_type}: {stats['successful']}/{stats['total']}")

    logger.info("\nTotal change statistics:")
    changes = statistics['total_changes']
    logger.info(f"  Test methods: +{changes['methods_added']} "
               f"~{changes['methods_modified']} "
               f"-{changes['methods_deleted']}")
    logger.info(f"  Test files: +{changes['files_added']} "
               f"~{changes['files_modified']} "
               f"-{changes['files_deleted']}")

    logger.info(f"\nResults saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
