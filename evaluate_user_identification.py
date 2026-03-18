#!/usr/bin/env python3
"""
User识别准确度评估工具
基于worktree中user的实际修改，评估识别过时测试用例的准确度
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

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from identify_evaluation import GTTestChangeExtractor
from utils.logger import setup_logger, get_logger


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='User识别准确度评估工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 评估user的识别准确度
  python evaluate_user_identification.py \
    --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
    --gt identify_evaluation/gt_changes_all.json \
    --output identify_evaluation/user_identification_results.json

  # 只评估特定项目
  python evaluate_user_identification.py \\
    --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \\
    --gt identify_evaluation/gt_changes_all.json \\
    --output results.json \\
    --project commons-csv
        '''
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='输入CSV文件路径（worktree_records.csv）')
    parser.add_argument('--gt', '-g', type=str, required=True,
                        help='Ground Truth文件路径')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='输出结果文件路径')
    parser.add_argument('--project', '-p', type=str,
                        help='只评估指定项目')
    parser.add_argument('--task-range', '-r', type=str,
                        help='任务ID范围（如 1-10）')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def read_worktree_records(csv_path: str) -> List[Dict]:
    """读取worktree_records.csv文件"""
    records = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records


def load_gt_data(gt_file: str) -> Dict:
    """加载Ground Truth数据"""
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
    提取user在worktree中的测试变更（包括未提交的修改）

    Args:
        worktree_path: worktree路径
        v_0_5_commit: V-0.5 commit hash（基准版本）
        logger: 日志记录器

    Returns:
        包含user修改信息的字典
    """
    if not os.path.exists(worktree_path):
        logger.warning(f"  Worktree路径不存在: {worktree_path}")
        return None

    try:
        repo = Repo(worktree_path)

        # 首先检查是否有未提交的修改（working directory changes）
        # 使用 git diff HEAD 来查看未提交的修改
        uncommitted_diff = repo.git.diff('HEAD', '--name-status', '--diff-filter=AMD')

        # 如果有未提交的修改，使用working directory作为比较目标
        if uncommitted_diff.strip():
            logger.debug(f"  检测到未提交的修改")
            # 获取相对于V-0.5的所有变更（包括未提交的）
            diff_output = repo.git.diff(v_0_5_commit, '--name-status', '--diff-filter=AMD')
            compare_target = None  # None表示working directory
        else:
            # 没有未提交的修改，使用HEAD
            logger.debug(f"  使用HEAD作为比较目标")
            diff_output = repo.git.diff(v_0_5_commit, 'HEAD', '--name-status', '--diff-filter=AMD')
            compare_target = 'HEAD'

        # 提取测试文件变更
        test_files = {}
        for line in diff_output.split('\n'):
            if not line.strip():
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            change_type = parts[0]
            file_path = parts[1]

            # 只关注测试文件
            if 'test' in file_path.lower() and file_path.endswith('.java'):
                test_files[file_path] = change_type

        if not test_files:
            logger.debug(f"  未检测到测试文件变更")
            return {
                'modified_files': [],
                'added_files': [],
                'deleted_files': []
            }

        logger.debug(f"  检测到 {len(test_files)} 个测试文件变更")

        # 分析每个测试文件的变更
        extractor = GTTestChangeExtractor(worktree_path)

        modified_files = []
        added_files = []
        deleted_files = []

        for file_path, change_type in test_files.items():
            if change_type == 'A':
                # 新增文件
                if compare_target:
                    file_info = extractor._analyze_added_file(file_path, compare_target)
                else:
                    # 从working directory读取
                    file_info = extractor._analyze_added_file_from_workdir(file_path)
                added_files.append(file_info)
            elif change_type == 'D':
                # 删除文件
                file_info = extractor._analyze_deleted_file(file_path, v_0_5_commit)
                deleted_files.append(file_info)
            elif change_type == 'M':
                # 修改文件
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
        logger.error(f"  提取user变更失败: {str(e)}")
        import traceback
        logger.debug(traceback.format_exc())
        return None


def extract_user_identified_tests(user_changes: Dict) -> Set[Tuple[str, str]]:
    """
    从user变更中提取识别出的过时测试

    特殊规则：
    - 修改的方法：正常计算
    - 删除的方法：正常计算
    - 新增的方法：按文件粒度，每个文件只算1个

    Returns:
        Set of (file_path, method_name) tuples
        对于新增方法，使用特殊标记 (file_path, '__FILE_LEVEL_ADD__')
    """
    identified = set()

    if not user_changes:
        return identified

    # 修改的文件中的修改和删除的方法
    for file_info in user_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # 修改的方法
        for method in file_info.get('modified_methods', []):
            identified.add((file_path, method))

        # 删除的方法
        for method in file_info.get('deleted_methods', []):
            identified.add((file_path, method))

        # 新增的方法：按文件粒度
        if file_info.get('added_methods'):
            identified.add((file_path, '__FILE_LEVEL_ADD__'))

    # 删除的文件中的所有方法
    for file_info in user_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            identified.add((file_path, method))

    # 新增的文件：按文件粒度
    for file_info in user_changes.get('added_files', []):
        file_path = file_info['file_path']
        if file_info.get('added_methods'):
            identified.add((file_path, '__FILE_LEVEL_ADD__'))

    return identified


def extract_gt_obsolete_tests(gt_data: Dict) -> Set[Tuple[str, str]]:
    """
    从GT数据中提取过时的测试方法

    过时测试定义：被修改或删除的测试方法

    特殊规则：
    - 新增的方法：按文件粒度，每个文件只算1个

    Returns:
        Set of (file_path, method_name) tuples
    """
    obsolete = set()

    if not gt_data or not gt_data.get('test_changes'):
        return obsolete

    test_changes = gt_data['test_changes']

    # 修改的文件
    for file_info in test_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # 修改的方法
        for method in file_info.get('modified_methods', []):
            obsolete.add((file_path, method))

        # 删除的方法
        for method in file_info.get('deleted_methods', []):
            obsolete.add((file_path, method))

        # 新增的方法：按文件粒度
        if file_info.get('added_methods'):
            obsolete.add((file_path, '__FILE_LEVEL_ADD__'))

    # 删除的文件
    for file_info in test_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            obsolete.add((file_path, method))

    # 新增的文件：按文件粒度
    for file_info in test_changes.get('added_files', []):
        file_path = file_info['file_path']
        if file_info.get('added_methods'):
            obsolete.add((file_path, '__FILE_LEVEL_ADD__'))

    return obsolete


def calculate_metrics(gt_tests: Set, user_tests: Set) -> Dict:
    """
    计算评估指标

    Args:
        gt_tests: Ground Truth中的过时测试集合
        user_tests: User识别出的测试集合

    Returns:
        包含Precision、Recall、F1等指标的字典
    """
    # True Positives: 正确识别的过时测试
    tp = len(gt_tests & user_tests)

    # False Positives: 错误识别的
    fp = len(user_tests - gt_tests)

    # False Negatives: 遗漏的过时测试
    fn = len(gt_tests - user_tests)

    # Precision: 识别出的测试中，真正过时的比例
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Recall: 所有过时测试中，被识别出的比例
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
    """评估所有任务"""
    results = []

    # 解析任务范围
    task_range_set = None
    if task_range:
        try:
            start, end = map(int, task_range.split('-'))
            task_range_set = set(range(start, end + 1))
        except ValueError:
            logger.warning(f"无效的任务范围格式: {task_range}")

    for i, record in enumerate(records):
        task_id = int(record['task_id'])
        project = record['project']
        worktree_path = record['worktree_path']
        v_0_5_commit = record['v_0_5_commit']
        v_0_commit = record['v_0_commit']
        task_type = record['type']

        # 项目过滤
        if project_filter and project != project_filter:
            continue

        # 任务范围过滤
        if task_range_set and task_id not in task_range_set:
            continue

        logger.info(f"[{i+1}/{len(records)}] 评估任务 {task_id} ({project}): {v_0_commit[:8]}")

        # 获取GT数据
        gt_key = (task_id, project)
        gt_data = gt_index.get(gt_key)

        if not gt_data:
            logger.warning(f"  未找到GT数据")
            continue

        # 提取user变更
        user_changes = extract_user_changes(worktree_path, v_0_5_commit, logger)

        if user_changes is None:
            logger.warning(f"  无法提取user变更")
            continue

        # 提取识别出的测试
        user_tests = extract_user_identified_tests(user_changes)
        gt_tests = extract_gt_obsolete_tests(gt_data)

        # 计算指标
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
    """聚合所有任务的指标"""
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

    # 按项目统计
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

    # 按类型统计
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
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("User识别准确度评估工具")
    logger.info("=" * 60)

    # 读取数据
    logger.info(f"读取CSV文件: {args.input}")
    records = read_worktree_records(args.input)
    logger.info(f"共读取 {len(records)} 条记录")

    logger.info(f"加载Ground Truth: {args.gt}")
    gt_index = load_gt_data(args.gt)
    logger.info(f"加载了 {len(gt_index)} 个GT任务")

    # 评估
    logger.info("\n开始评估...")
    results = evaluate_all_tasks(records, gt_index, args.project, args.task_range, logger)

    if not results:
        logger.error("没有成功评估的任务")
        return 1

    # 聚合指标
    logger.info("\n计算聚合指标...")
    aggregated = aggregate_metrics(results)

    # 保存结果
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

    # 输出结果
    logger.info("\n" + "=" * 60)
    logger.info("评估完成")
    logger.info("=" * 60)

    overall = aggregated['overall']
    logger.info(f"\n总体指标 (共 {overall['total_tasks']} 个任务):")
    logger.info(f"  GT过时测试总数: {overall['total_gt_obsolete_tests']}")
    logger.info(f"  User识别测试总数: {overall['total_user_identified_tests']}")
    logger.info(f"  正确识别 (TP): {overall['total_true_positives']}")
    logger.info(f"  错误识别 (FP): {overall['total_false_positives']}")
    logger.info(f"  遗漏 (FN): {overall['total_false_negatives']}")

    logger.info(f"\n宏平均 (Macro Average):")
    logger.info(f"  Precision: {overall['macro_precision']:.2%}")
    logger.info(f"  Recall: {overall['macro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['macro_f1']:.2%}")

    logger.info(f"\n微平均 (Micro Average):")
    logger.info(f"  Precision: {overall['micro_precision']:.2%}")
    logger.info(f"  Recall: {overall['micro_recall']:.2%}")
    logger.info(f"  F1 Score: {overall['micro_f1']:.2%}")

    logger.info(f"\n按项目统计:")
    for project, metrics in aggregated['by_project'].items():
        logger.info(f"  {project} ({metrics['tasks']} 任务):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\n按类型统计:")
    for task_type, metrics in aggregated['by_type'].items():
        logger.info(f"  {task_type} ({metrics['tasks']} 任务):")
        logger.info(f"    Precision: {metrics['precision']:.2%}, "
                   f"Recall: {metrics['recall']:.2%}, "
                   f"F1: {metrics['f1_score']:.2%}")

    logger.info(f"\n详细结果已保存到: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
