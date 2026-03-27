#!/usr/bin/env python3
"""
User Identification Accuracy Evaluation Tool
Evaluates the accuracy of identifying outdated test cases based on the actual modifications made by users in worktrees
"""

import sys
import os
import csv
import json
import argparse
from datetime import datetime
from typing import Dict, List, Set, Tuple
from collections import defaultdict
from git import Repo

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from identify_evaluation import GTTestChangeExtractor
from utils.logger import setup_logger, get_logger


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='User Identification Accuracy Evaluation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Evaluate user's identification accuracy
  python evaluate_user_identification.py \
    --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
    --gt identify_evaluation/gt_changes_all.json \
    --output identify_evaluation/user_identification_results.json

  # Evaluate only a specific project
  python evaluate_user_identification.py \\
    --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \\
    --gt identify_evaluation/gt_changes_all.json \\
    --output results.json \\
    --project commons-csv
        '''
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='Input CSV file path (worktree_records.csv)')
    parser.add_argument('--gt', '-g', type=str, required=True,
                        help='Ground Truth file path')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='Output result file path')
    parser.add_argument('--project', '-p', type=str,
                        help='Evaluate only the specified project')
    parser.add_argument('--task-range', '-r', type=str,
                        help='Task ID range (e.g. 1-10)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging output')

    return parser.parse_args()


def read_worktree_records(csv_path: str) -> List[Dict]:
    """Read worktree_records.csv file"""
    records = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records


def load_gt_data(gt_file: str) -> Dict:
    """loadGround Truthdata"""
    with open(gt_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 构建索引：(task_id, project) -> gt_data
    gt_index = {}
    for result in data.get('results', []):
        key = (result['task_id'], result['project'])
        gt_index[key] = result

    return gt_index


def extract_user_changes(worktree_path: str, v_0_5_commit: str, logger) -> Dict:
    """
    提取userinworktree中的测试变更（包括未commit的修改）

    Args:
        worktree_path: worktreepath
        v_0_5_commit: V-0.5 commit hash（基准version）
        logger: logrecord器

    Returns:
        包含user修改information的字典
    """
    if not os.path.exists(worktree_path):
        logger.warning(f"  Worktreepath不存in: {worktree_path}")
        return None

    try:
        repo = Repo(worktree_path)

        # 首先check是否有未commit的修改（working directory changes）
        # 使用 git diff HEAD 来查看未commit的修改
        uncommitted_diff = repo.git.diff('HEAD', '--name-status', '--diff-filter=AMD')

        # 如果有未commit的修改，使用working directory作为比较目标
        if uncommitted_diff.strip():
            logger.debug(f"  detect到未commit的修改")
            # get相对于V-0.5的所有变更（包括未commit的）
            diff_output = repo.git.diff(v_0_5_commit, '--name-status', '--diff-filter=AMD')
            compare_target = None  # None表示working directory
        else:
            # 没有未commit的修改，使用HEAD
            logger.debug(f"  使用HEAD作为比较目标")
            diff_output = repo.git.diff(v_0_5_commit, 'HEAD', '--name-status', '--diff-filter=AMD')
            compare_target = 'HEAD'

        # 提取test files变更
        test_files = {}
        for line in diff_output.split('\n'):
            if not line.strip():
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            change_type = parts[0]
            file_path = parts[1]

            # 只关注test files
            if 'test' in file_path.lower() and file_path.endswith('.java'):
                test_files[file_path] = change_type

        if not test_files:
            logger.debug(f"  未detect到test files变更")
            return {
                'modified_files': [],
                'added_files': [],
                'deleted_files': []
            }

        logger.debug(f"  detect到 {len(test_files)} 个test files变更")

        # 分析每个test files的变更
        extractor = GTTestChangeExtractor(worktree_path)

        modified_files = []
        added_files = []
        deleted_files = []

        for file_path, change_type in test_files.items():
            if change_type == 'A':
                # 新增file
                if compare_target:
                    file_info = extractor._analyze_added_file(file_path, compare_target)
                else:
                    # 从working directory读取
                    file_info = extractor._analyze_added_file_from_workdir(file_path)
                added_files.append(file_info)
            elif change_type == 'D':
                # deletefile
                file_info = extractor._analyze_deleted_file(file_path, v_0_5_commit)
                deleted_files.append(file_info)
            elif change_type == 'M':
                # 修改file
                if compare_target:
                    file_info = extractor._analyze_modified_file(file_path, v_0_5_commit, compare_target)
                else:
                    # 与working directory比较
                    file_info = extractor._analyze_modified_file_with_workdir(file_path, v_0_5_commit)
                if file_info:
                    modified_files.append(file_info)

        return {
            'modified_files': modified_files,
            'added_files': added_files,
            'deleted_files': deleted_files
        }

    except Exception as e:
        logger.error(f"  提取user变更Failed: {str(e)}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def extract_user_identified_tests(user_changes: Dict) -> Set[Tuple[str, str]]:
    """
    从user变更中提取identify出的obsolete tests

    特殊规则：
    - 修改的method：正常calculate
    - delete的method：正常calculate
    - 新增的method：按file粒度，每个file只算1个

    Returns:
        Set of (file_path, method_name) tuples
        对于新增method，使用特殊标记 (file_path, '__FILE_LEVEL_ADD__')
    """
    identified = set()

    if not user_changes:
        return identified

    # 修改的file中的修改和delete的method
    for file_info in user_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # 修改的method
        for method in file_info.get('modified_methods', []):
            identified.add((file_path, method))

        # delete的method
        for method in file_info.get('deleted_methods', []):
            identified.add((file_path, method))

        # 新增的method：按file粒度
        if file_info.get('added_methods'):
            identified.add((file_path, '__FILE_LEVEL_ADD__'))

    # delete的file中的所有method
    for file_info in user_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            identified.add((file_path, method))

    # 新增的file：按file粒度
    for file_info in user_changes.get('added_files', []):
        file_path = file_info['file_path']
        if file_info.get('added_methods'):
            identified.add((file_path, '__FILE_LEVEL_ADD__'))

    return identified


def extract_gt_obsolete_tests(gt_data: Dict) -> Set[Tuple[str, str]]:
    """
    从GTdata中提取过时的测试method

    obsolete tests定义：被修改或delete的测试method

    特殊规则：
    - 新增的method：按file粒度，每个file只算1个

    Returns:
        Set of (file_path, method_name) tuples
    """
    obsolete = set()

    if not gt_data or not gt_data.get('test_changes'):
        return obsolete

    test_changes = gt_data['test_changes']

    # 修改的file
    for file_info in test_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # 修改的method
        for method in file_info.get('modified_methods', []):
            obsolete.add((file_path, method))

        # delete的method
        for method in file_info.get('deleted_methods', []):
            obsolete.add((file_path, method))

        # 新增的method：按file粒度
        if file_info.get('added_methods'):
            obsolete.add((file_path, '__FILE_LEVEL_ADD__'))

    # delete的file
    for file_info in test_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            obsolete.add((file_path, method))

    # 新增的file：按file粒度
    for file_info in test_changes.get('added_files', []):
        file_path = file_info['file_path']
        if file_info.get('added_methods'):
            obsolete.add((file_path, '__FILE_LEVEL_ADD__'))

    return obsolete


def calculate_metrics(gt_tests: Set, user_tests: Set) -> Dict:
    """
    calculateevaluate指标

    Args:
        gt_tests: Ground Truth中的obsolete tests集合
        user_tests: Useridentify出的测试集合

    Returns:
        包含Precision、Recall、F1等指标的字典
    """
    # True Positives: 正确identify的obsolete tests
    tp = len(gt_tests & user_tests)

    # False Positives: erroridentify的
    fp = len(user_tests - gt_tests)

    # False Negatives: 遗漏的obsolete tests
    fn = len(gt_tests - user_tests)

    # Precision: identify出的测试中，真正过时的比例
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Recall: 所有obsolete tests中，被identify出的比例
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    # F1 Score
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        'true_positives': tp,
        'false_positives': fp,
        'false_negatives': fn,
        'precision': precision,
        'recall': recall,
        'f1_score': f1,
        'gt_total': len(gt_tests),
        'user_total': len(user_tests)
    }


def evaluate_all_tasks(records: List[Dict], gt_index: Dict, project_filter: str, task_range: str, logger) -> List[Dict]:
    """evaluate所有task"""
    results = []

    # parsetask范围
    task_range_set = None
    if task_range:
        try:
            start, end = map(int, task_range.split('-'))
            task_range_set = set(range(start, end + 1))
        except ValueError:
            logger.warning(f"无效的task范围format: {task_range}")

    for i, record in enumerate(records):
        task_id = int(record['task_id'])
        project = record['project']
        worktree_path = record['worktree_path']
        v_0_5_commit = record['v_0_5_commit']
        v_0_commit = record['v_0_commit']
        task_type = record['type']

        # project过滤
        if project_filter and project != project_filter:
            continue

        # task范围过滤
        if task_range_set and task_id not in task_range_set:
            continue

        logger.info(f"[{i+1}/{len(records)}] evaluatetask {task_id} ({project}): {v_0_commit[:8]}")

        # getGTdata
        gt_key = (task_id, project)
        gt_data = gt_index.get(gt_key)

        if not gt_data:
            logger.warning(f"  未foundGTdata")
            continue

        # 提取user变更
        user_changes = extract_user_changes(worktree_path, v_0_5_commit, logger)

        if user_changes is None:
            logger.warning(f"  无法提取user变更")
            continue

        # 提取identify出的测试
        user_tests = extract_user_identified_tests(user_changes)
        gt_tests = extract_gt_obsolete_tests(gt_data)

        # calculate指标
        metrics = calculate_metrics(gt_tests, user_tests)

        logger.info(f"  GT: {metrics['gt_total']}, User: {metrics['user_total']}, "
                   f"TP: {metrics['true_positives']}")
        logger.info(f"  Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

        results.append({
            'task_id': task_id,
            'project': project,
            'type': task_type,
            'v_0_commit': v_0_commit,
            'metrics': metrics,
            'details': {
                'gt_tests': sorted(list(gt_tests)),
                'user_tests': sorted(list(user_tests)),
                'true_positives': sorted(list(gt_tests & user_tests)),
                'false_positives': sorted(list(user_tests - gt_tests)),
                'false_negatives': sorted(list(gt_tests - user_tests))
            }
        })

    return results


def aggregate_metrics(results: List[Dict]) -> Dict:
    """聚合所有task的指标"""
    if not results:
        return {}

    total_tp = sum(r['metrics']['true_positives'] for r in results)
    total_fp = sum(r['metrics']['false_positives'] for r in results)
    total_fn = sum(r['metrics']['false_negatives'] for r in results)
    total_gt = sum(r['metrics']['gt_total'] for r in results)
    total_user = sum(r['metrics']['user_total'] for r in results)

    # 宏平均
    macro_precision = sum(r['metrics']['precision'] for r in results) / len(results)
    macro_recall = sum(r['metrics']['recall'] for r in results) / len(results)
    macro_f1 = sum(r['metrics']['f1_score'] for r in results) / len(results)

    # 微平均
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if (micro_precision + micro_recall) > 0 else 0

    # 按projectstatistics
    by_project = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'gt': 0, 'user': 0, 'count': 0})
    for r in results:
        project = r['project']
        by_project[project]['tp'] += r['metrics']['true_positives']
        by_project[project]['fp'] += r['metrics']['false_positives']
        by_project[project]['fn'] += r['metrics']['false_negatives']
        by_project[project]['gt'] += r['metrics']['gt_total']
        by_project[project]['user'] += r['metrics']['user_total']
        by_project[project]['count'] += 1

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
            'user_total': stats['user']
        }

    # 按class型statistics
    by_type = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'gt': 0, 'user': 0, 'count': 0})
    for r in results:
        task_type = r.get('type', 'unknown')
        by_type[task_type]['tp'] += r['metrics']['true_positives']
        by_type[task_type]['fp'] += r['metrics']['false_positives']
        by_type[task_type]['fn'] += r['metrics']['false_negatives']
        by_type[task_type]['gt'] += r['metrics']['gt_total']
        by_type[task_type]['user'] += r['metrics']['user_total']
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
            'user_total': stats['user']
        }

    return {
        'overall': {
            'total_tasks': len(results),
            'total_true_positives': total_tp,
            'total_false_positives': total_fp,
            'total_false_negatives': total_fn,
            'total_gt_obsolete_tests': total_gt,
            'total_user_identified_tests': total_user,
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
    """main function"""
    args = parse_args()

    # set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Useridentify准确度evaluate工具")
    logger.info("=" * 60)

    # 读取data
    logger.info(f"读取CSVfile: {args.input}")
    records = read_worktree_records(args.input)
    logger.info(f"共读取 {len(records)} 条record")

    logger.info(f"loadGround Truth: {args.gt}")
    gt_index = load_gt_data(args.gt)
    logger.info(f"Loaded {len(gt_index)} 个GTtask")

    # evaluate
    logger.info("\nstartevaluate...")
    results = evaluate_all_tasks(records, gt_index, args.project, args.task_range, logger)

    if not results:
        logger.error("没有successevaluate的task")
        return 1

    # 聚合指标
    logger.info("\ncalculate聚合指标...")
    aggregated = aggregate_metrics(results)

    # save results
    output_data = {
        'metadata': {
            'evaluation_time': datetime.now().isoformat(),
            'input_file': args.input,
            'gt_file': args.gt,
            'project_filter': args.project,
            'total_tasks': len(results)
        },
        'aggregated_metrics': aggregated,
        'task_results': results
    }

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # outputresult
    logger.info("\n" + "=" * 60)
    logger.info("evaluatecomplete")
    logger.info("=" * 60)

    overall = aggregated['overall']
    logger.info(f"\n总体指标 (共 {overall['total_tasks']} 个task):")
    logger.info(f"  GTobsolete tests总数: {overall['total_gt_obsolete_tests']}")
    logger.info(f"  Useridentify测试总数: {overall['total_user_identified_tests']}")
    logger.info(f"  正确identify (TP): {overall['total_true_positives']}")
    logger.info(f"  erroridentify (FP): {overall['total_false_positives']}")
    logger.info(f"  遗漏 (FN): {overall['total_false_negatives']}")

    logger.info(f"\n宏平均 (Macro Average):")
    logger.info(f"  Precision: {overall['macro_precision']:.2%}")
    logger.info(f"  Recall: {overall['macro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['macro_f1']:.2%}")

    logger.info(f"\n微平均 (Micro Average):")
    logger.info(f"  Precision: {overall['micro_precision']:.2%}")
    logger.info(f"  Recall: {overall['micro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['micro_f1']:.2%}")

    logger.info(f"\n按projectstatistics:")
    for project, metrics in aggregated['by_project'].items():
        logger.info(f"  {project} ({metrics['tasks']} task):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\n按class型statistics:")
    for task_type, metrics in aggregated['by_type'].items():
        logger.info(f"  {task_type} ({metrics['tasks']} task):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\n详细Results saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
