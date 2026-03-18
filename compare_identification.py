#!/usr/bin/env python3
"""
识别结果比较工具
将识别方法的结果与Ground Truth进行对比，计算Precision、Recall、F1等指标
"""

import sys
import os
import json
import argparse
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import setup_logger, get_logger


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='识别结果比较工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 比较识别结果与GT
  python compare_identification.py \\
    --gt identify_evaluation/gt_changes_all.json \\
    --predicted method_results.json \\
    --output comparison_results.json

  # 只比较特定项目
  python compare_identification.py \\
    --gt identify_evaluation/gt_changes_all.json \\
    --predicted method_results.json \\
    --output comparison_results.json \\
    --project commons-csv
        '''
    )

    parser.add_argument('--gt', '-g', type=str, required=True,
                        help='Ground Truth文件路径')
    parser.add_argument('--predicted', '-p', type=str, required=True,
                        help='识别方法结果文件路径')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='输出比较结果文件路径')
    parser.add_argument('--project', type=str,
                        help='只比较指定项目')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def load_gt_data(gt_file: str) -> Dict:
    """加载Ground Truth数据"""
    with open(gt_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_predicted_data(predicted_file: str) -> Dict:
    """
    加载识别方法的结果数据

    预期格式:
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
    从GT数据中提取过时的测试方法

    过时测试定义：被修改或删除的测试方法

    Returns:
        Set of (file_path, method_name) tuples
    """
    obsolete_tests = set()

    if not task_data.get('test_changes'):
        return obsolete_tests

    test_changes = task_data['test_changes']

    # 修改的文件中的修改和删除的方法
    for file_info in test_changes.get('modified_files', []):
        file_path = file_info['file_path']

        # 修改的方法
        for method in file_info.get('modified_methods', []):
            obsolete_tests.add((file_path, method))

        # 删除的方法
        for method in file_info.get('deleted_methods', []):
            obsolete_tests.add((file_path, method))

    # 删除的文件中的所有方法
    for file_info in test_changes.get('deleted_files', []):
        file_path = file_info['file_path']
        for method in file_info.get('deleted_methods', []):
            obsolete_tests.add((file_path, method))

    return obsolete_tests


def extract_predicted_tests(task_data: Dict) -> Set[Tuple[str, str]]:
    """
    从识别结果中提取识别出的测试方法

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
    计算评估指标

    Args:
        gt_tests: Ground Truth中的过时测试集合
        predicted_tests: 识别方法识别出的测试集合

    Returns:
        包含Precision、Recall、F1等指标的字典
    """
    # True Positives: 正确识别的过时测试
    tp = len(gt_tests & predicted_tests)

    # False Positives: 错误识别的（实际不过时但被识别为过时）
    fp = len(predicted_tests - gt_tests)

    # False Negatives: 遗漏的过时测试
    fn = len(gt_tests - predicted_tests)

    # True Negatives: 无法直接计算（需要知道所有非过时测试）

    # Precision: 识别出的测试中，真正过时的比例
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Recall: 所有过时测试中，被识别出的比例
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    # F1 Score: Precision和Recall的调和平均
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
    比较所有任务的识别结果

    Args:
        gt_data: Ground Truth数据
        predicted_data: 识别方法结果数据
        project_filter: 项目过滤器

    Returns:
        比较结果字典
    """
    logger = get_logger()

    # 构建predicted数据的索引
    predicted_index = {}
    for task in predicted_data.get('results', []):
        key = (task['task_id'], task['project'])
        predicted_index[key] = task

    task_results = []

    for gt_task in gt_data.get('results', []):
        task_id = gt_task['task_id']
        project = gt_task['project']

        # 项目过滤
        if project_filter and project != project_filter:
            continue

        logger.info(f"比较任务 {task_id} ({project})")

        # 提取GT中的过时测试
        gt_tests = extract_gt_obsolete_tests(gt_task)

        # 查找对应的predicted数据
        key = (task_id, project)
        predicted_task = predicted_index.get(key)

        if not predicted_task:
            logger.warning(f"  未找到任务 {task_id} 的识别结果")
            predicted_tests = set()
        else:
            predicted_tests = extract_predicted_tests(predicted_task)

        # 计算指标
        metrics = calculate_metrics(gt_tests, predicted_tests)

        logger.info(f"  GT过时测试: {metrics['gt_total']}, "
                   f"识别出: {metrics['predicted_total']}, "
                   f"正确: {metrics['true_positives']}")
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
    聚合所有任务的指标

    Args:
        task_results: 任务结果列表

    Returns:
        聚合后的指标
    """
    total_tp = sum(r['metrics']['true_positives'] for r in task_results)
    total_fp = sum(r['metrics']['false_positives'] for r in task_results)
    total_fn = sum(r['metrics']['false_negatives'] for r in task_results)
    total_gt = sum(r['metrics']['gt_total'] for r in task_results)
    total_predicted = sum(r['metrics']['predicted_total'] for r in task_results)

    # 宏平均（Macro Average）：每个任务的指标平均
    macro_precision = sum(r['metrics']['precision'] for r in task_results) / len(task_results) if task_results else 0
    macro_recall = sum(r['metrics']['recall'] for r in task_results) / len(task_results) if task_results else 0
    macro_f1 = sum(r['metrics']['f1_score'] for r in task_results) / len(task_results) if task_results else 0

    # 微平均（Micro Average）：所有任务的TP/FP/FN总和计算
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if (micro_precision + micro_recall) > 0 else 0

    # 按项目统计
    by_project = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0, 'gt': 0, 'pred': 0, 'count': 0})
    for r in task_results:
        project = r['project']
        by_project[project]['tp'] += r['metrics']['true_positives']
        by_project[project]['fp'] += r['metrics']['false_positives']
        by_project[project]['fn'] += r['metrics']['false_negatives']
        by_project[project]['gt'] += r['metrics']['gt_total']
        by_project[project]['pred'] += r['metrics']['predicted_total']
        by_project[project]['count'] += 1

    # 计算每个项目的指标
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

    # 按类型统计
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
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("识别结果比较工具")
    logger.info("=" * 60)

    # 加载数据
    logger.info(f"加载Ground Truth: {args.gt}")
    gt_data = load_gt_data(args.gt)

    logger.info(f"加载识别结果: {args.predicted}")
    predicted_data = load_predicted_data(args.predicted)

    # 比较任务
    logger.info("\n开始比较...")
    task_results = compare_tasks(gt_data, predicted_data, args.project)

    # 聚合指标
    logger.info("\n计算聚合指标...")
    aggregated = aggregate_metrics(task_results)

    # 保存结果
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

    # 输出结果
    logger.info("\n" + "=" * 60)
    logger.info("比较完成")
    logger.info("=" * 60)

    overall = aggregated['overall']
    logger.info(f"\n总体指标 (共 {overall['total_tasks']} 个任务):")
    logger.info(f"  GT过时测试总数: {overall['total_gt_obsolete_tests']}")
    logger.info(f"  识别出的测试总数: {overall['total_predicted_tests']}")
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
