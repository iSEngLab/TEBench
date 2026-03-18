#!/usr/bin/env python3
"""
Ground Truth测试变更提取工具
从worktree_records.csv中读取任务信息，提取每个任务的GT测试变更
"""

import sys
import os
import csv
import json
import argparse
from datetime import datetime
from typing import List, Dict

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from identify_evaluation import GTTestChangeExtractor
from utils.logger import setup_logger, get_logger


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Ground Truth测试变更提取工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 从CSV文件提取GT变更
  python extract_gt_changes.py --input /path/to/worktree_records.csv --output gt_changes.json

  # 只处理特定项目
  python extract_gt_changes.py --input records.csv --output gt_changes.json --project commons-csv

  # 只处理特定任务ID范围
  python extract_gt_changes.py --input records.csv --output gt_changes.json --task-range 1-10
        '''
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='输入CSV文件路径（worktree_records.csv）')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='输出JSON文件路径')
    parser.add_argument('--project', '-p', type=str, nargs='+',
                        help='只处理指定项目（如 commons-csv），支持多个项目')
    parser.add_argument('--task-range', '-r', type=str,
                        help='任务ID范围（如 1-10）')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def read_worktree_records(csv_path: str) -> List[Dict]:
    """
    读取worktree_records.csv文件

    Args:
        csv_path: CSV文件路径

    Returns:
        任务记录列表
    """
    records = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)

    return records


def filter_records(records: List[Dict], project: List[str] = None, task_range: str = None) -> List[Dict]:
    """
    过滤任务记录

    Args:
        records: 所有记录
        project: 项目名称列表过滤
        task_range: 任务ID范围（如 "1-10"）

    Returns:
        过滤后的记录
    """
    filtered = records

    # 按项目过滤
    if project:
        filtered = [r for r in filtered if r['project'] in project]

    # 按任务ID范围过滤
    if task_range:
        try:
            start, end = map(int, task_range.split('-'))
            filtered = [r for r in filtered if start <= int(r['task_id']) <= end]
        except ValueError:
            print(f"警告: 无效的任务范围格式: {task_range}")

    return filtered


def extract_all_gt_changes(records: List[Dict], logger) -> List[Dict]:
    """
    提取所有任务的GT变更

    Args:
        records: 任务记录列表
        logger: 日志记录器

    Returns:
        GT变更信息列表
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

        logger.info(f"[{i+1}/{len(records)}] 处理任务 {task_id} ({project}): {v_0[:8]}")

        # 检查项目路径是否存在
        if not os.path.exists(project_path):
            logger.warning(f"  项目路径不存在: {project_path}")
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

        # 如果切换了项目，创建新的提取器
        if project != current_project:
            current_project = project
            extractor = GTTestChangeExtractor(project_path)
            logger.info(f"  切换到项目: {project}")

        try:
            # 提取测试变更
            test_changes = extractor.extract_test_changes(v_minus_1, v_0)

            result = {
                'task_id': int(task_id),
                'project': project,
                'v_minus_1_commit': v_minus_1,
                'v_0_commit': v_0,
                'type': task_type,
                'test_changes': test_changes
            }

            # 输出摘要
            summary = test_changes['summary']
            logger.info(f"  ✓ 方法: +{summary['total_test_methods_added']} "
                       f"~{summary['total_test_methods_modified']} "
                       f"-{summary['total_test_methods_deleted']}")
            logger.info(f"  ✓ 文件: +{summary['total_test_files_added']} "
                       f"~{summary['total_test_files_modified']} "
                       f"-{summary['total_test_files_deleted']}")

            results.append(result)

        except Exception as e:
            logger.error(f"  ✗ 提取失败: {str(e)}")
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
    生成统计信息

    Args:
        results: GT变更结果列表

    Returns:
        统计信息字典
    """
    total_tasks = len(results)
    successful = sum(1 for r in results if 'error' not in r)
    failed = total_tasks - successful

    # 按项目统计
    projects = {}
    for r in results:
        project = r['project']
        if project not in projects:
            projects[project] = {'total': 0, 'successful': 0}
        projects[project]['total'] += 1
        if 'error' not in r:
            projects[project]['successful'] += 1

    # 按类型统计
    types = {}
    for r in results:
        task_type = r['type']
        if task_type not in types:
            types[task_type] = {'total': 0, 'successful': 0}
        types[task_type]['total'] += 1
        if 'error' not in r:
            types[task_type]['successful'] += 1

    # 变更统计
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
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Ground Truth测试变更提取工具")
    logger.info("=" * 60)

    # 读取CSV文件
    logger.info(f"读取CSV文件: {args.input}")
    records = read_worktree_records(args.input)
    logger.info(f"共读取 {len(records)} 条记录")

    # 过滤记录
    filtered_records = filter_records(records, args.project, args.task_range)
    logger.info(f"过滤后剩余 {len(filtered_records)} 条记录")

    if not filtered_records:
        logger.error("没有符合条件的记录")
        return 1

    # 提取GT变更
    logger.info("\n开始提取GT变更...")
    results = extract_all_gt_changes(filtered_records, logger)

    # 生成统计信息
    statistics = generate_statistics(results)

    # 保存结果
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

    # 输出统计
    logger.info("\n" + "=" * 60)
    logger.info("提取完成")
    logger.info("=" * 60)
    logger.info(f"总任务数: {statistics['total_tasks']}")
    logger.info(f"成功: {statistics['successful']}")
    logger.info(f"失败: {statistics['failed']}")

    logger.info("\n按项目统计:")
    for project, stats in statistics['by_project'].items():
        logger.info(f"  {project}: {stats['successful']}/{stats['total']}")

    logger.info("\n按类型统计:")
    for task_type, stats in statistics['by_type'].items():
        logger.info(f"  {task_type}: {stats['successful']}/{stats['total']}")

    logger.info("\n总变更统计:")
    changes = statistics['total_changes']
    logger.info(f"  测试方法: +{changes['methods_added']} "
               f"~{changes['methods_modified']} "
               f"-{changes['methods_deleted']}")
    logger.info(f"  测试文件: +{changes['files_added']} "
               f"~{changes['files_modified']} "
               f"-{changes['files_deleted']}")

    logger.info(f"\n结果已保存到: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
