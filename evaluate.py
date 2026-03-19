#!/usr/bin/env python3
"""
TUBench Evaluation Tool - 评估工具主入口
用于评估过时测试用例修复方法的效果
"""

import sys
import os
import json
import argparse
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, AnalysisConfig
from utils.logger import setup_logger, get_logger
from update_evaluation import EvaluationOrchestrator, WorktreeManager


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='TUBench Evaluation Tool - 过时测试用例修复评估工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 准备单个评估任务
  python evaluate.py prepare --project /path/to/commons-csv --commit abc123

  # 执行评估
  python evaluate.py run --worktree /tmp/tubench_eval/commons-csv_abc123_eval

  # 批量评估
  python evaluate.py run-batch --input eval_tasks.json --output eval_results.json

  # 清理worktree
  python evaluate.py cleanup --worktree /tmp/tubench_eval/commons-csv_abc123_eval
  python evaluate.py cleanup --all --project /path/to/commons-csv
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # prepare 命令
    prepare_parser = subparsers.add_parser('prepare', help='准备评估环境')
    prepare_parser.add_argument('--project', '-p', type=str, required=True,
                                help='项目路径')
    prepare_parser.add_argument('--commit', '-c', type=str, required=True,
                                help='GT commit hash')
    prepare_parser.add_argument('--output-dir', '-o', type=str,
                                help='worktree输出目录')
    prepare_parser.add_argument('--cache-dir', type=str,
                                help='缓存目录（用于读取V-0.5信息）')

    # prepare-batch 命令
    prepare_batch_parser = subparsers.add_parser('prepare-batch', help='批量准备评估环境')
    prepare_batch_parser.add_argument('--project', '-p', type=str, required=True,
                                      help='项目路径')
    prepare_batch_parser.add_argument('--input', '-i', type=str, required=True,
                                      help='commit列表文件（JSON格式）')
    prepare_batch_parser.add_argument('--output-dir', '-o', type=str,
                                      help='worktree输出目录')

    # run 命令
    run_parser = subparsers.add_parser('run', help='执行评估')
    run_parser.add_argument('--worktree', '-w', type=str, required=True,
                            help='worktree路径')
    run_parser.add_argument('--gt-commit', '-g', type=str, required=True,
                            help='GT commit hash')
    run_parser.add_argument('--output', '-o', type=str,
                            help='结果输出文件')

    # run-batch 命令
    run_batch_parser = subparsers.add_parser('run-batch', help='批量执行评估')
    run_batch_parser.add_argument('--input', '-i', type=str, required=True,
                                  help='评估任务文件（JSON格式）')
    run_batch_parser.add_argument('--output', '-o', type=str, required=True,
                                  help='结果输出文件')
    run_batch_parser.add_argument('--project', '-p', type=str,
                                  help='项目路径（如果任务文件中未指定）')

    # report 命令
    report_parser = subparsers.add_parser('report', help='生成评估报告')
    report_parser.add_argument('--input', '-i', type=str, required=True,
                               help='评估结果文件')
    report_parser.add_argument('--format', '-f', type=str, choices=['json', 'csv'],
                               default='json', help='输出格式')

    # cleanup 命令
    cleanup_parser = subparsers.add_parser('cleanup', help='清理worktree')
    cleanup_parser.add_argument('--worktree', '-w', type=str,
                                help='指定worktree路径')
    cleanup_parser.add_argument('--all', action='store_true',
                                help='清理所有评估worktree')
    cleanup_parser.add_argument('--project', '-p', type=str,
                                help='项目路径（与--all一起使用）')

    # 通用参数
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def cmd_prepare(args, logger):
    """准备评估环境"""
    project_path = os.path.abspath(args.project)

    if not os.path.exists(project_path):
        logger.error(f"项目路径不存在: {project_path}")
        return 1

    # 创建WorktreeManager
    eval_dir = args.output_dir or WorktreeManager.DEFAULT_EVAL_DIR
    manager = WorktreeManager(project_path, eval_dir)

    # 准备worktree
    cache_dir = args.cache_dir or os.path.join(AnalysisConfig.CACHE_DIR, os.path.basename(project_path))
    result = manager.prepare_evaluation_worktree(args.commit, cache_dir)

    if result['success']:
        print(f"\n✓ 创建评估worktree: {result['worktree_path']}")
        print(f"✓ V-0.5分支: {result['v05_branch']} ({result['v05_commit'][:8]})")
        print(f"✓ 基于parent: {result['parent_commit'][:8]}")
        print(f"\n请在以下目录中修改测试代码:")
        print(f"  {result['worktree_path']}")
        print(f"\n修改完成后运行:")
        print(f"  python evaluate.py run --worktree {result['worktree_path']} --gt-commit {args.commit}")
        return 0
    else:
        logger.error(f"准备失败: {result.get('error')}")
        return 1


def cmd_prepare_batch(args, logger):
    """批量准备评估环境"""
    project_path = os.path.abspath(args.project)

    if not os.path.exists(project_path):
        logger.error(f"项目路径不存在: {project_path}")
        return 1

    # 读取commit列表
    with open(args.input, 'r') as f:
        data = json.load(f)

    commits = data.get('commits', data) if isinstance(data, dict) else data

    eval_dir = args.output_dir or WorktreeManager.DEFAULT_EVAL_DIR
    manager = WorktreeManager(project_path, eval_dir)
    cache_dir = os.path.join(AnalysisConfig.CACHE_DIR, os.path.basename(project_path))

    results = []
    for i, commit in enumerate(commits):
        commit_hash = commit if isinstance(commit, str) else commit.get('commit')
        logger.info(f"[{i+1}/{len(commits)}] 准备 {commit_hash[:8]}...")

        result = manager.prepare_evaluation_worktree(commit_hash, cache_dir)
        results.append({
            'commit': commit_hash,
            'success': result['success'],
            'worktree_path': result.get('worktree_path'),
            'error': result.get('error')
        })

    # 输出结果
    successful = sum(1 for r in results if r['success'])
    print(f"\n准备完成: {successful}/{len(commits)} 成功")

    # 保存任务文件
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
    print(f"任务文件已保存: {tasks_file}")

    return 0


def cmd_run(args, logger):
    """执行评估"""
    worktree_path = os.path.abspath(args.worktree)
    gt_commit = args.gt_commit

    if not os.path.exists(worktree_path):
        logger.error(f"worktree路径不存在: {worktree_path}")
        return 1

    # 获取项目路径（从worktree的git配置中获取原始仓库路径）
    from git import Repo
    worktree_repo = Repo(worktree_path)
    git_common_dir = worktree_repo.git.rev_parse('--git-common-dir')
    project_path = os.path.dirname(git_common_dir)

    # 创建评估器
    orchestrator = EvaluationOrchestrator(project_path)

    # 执行评估
    logger.info("开始评估...")
    result = orchestrator.run_evaluation(worktree_path, gt_commit)

    # 输出结果
    print("\n" + "=" * 60)
    print("评估结果")
    print("=" * 60)

    if result['success']:
        print(f"✓ 评估成功")
        print(f"\nGT Commit: {result['gt_commit'][:8]}")
        print(f"V-0.5 Commit: {result.get('v05_commit', 'N/A')[:8] if result.get('v05_commit') else 'N/A'}")

        exec_result = result['evaluation']['executability']
        print(f"\n[可执行性]")
        print(f"  编译: {'✓ 成功' if exec_result.get('compile_success') else '✗ 失败'}")
        print(f"  测试: {'✓ 成功' if exec_result.get('test_success') else '✗ 失败'}")
        if exec_result.get('test_results'):
            tr = exec_result['test_results']
            print(f"  测试统计: {tr.get('passed', 0)} 通过, {tr.get('failed', 0)} 失败, {tr.get('errors', 0)} 错误")

        cov_result = result['evaluation']['coverage_overlap']
        print(f"\n[覆盖增量重合度]")
        print(f"  行覆盖重合度: {cov_result.get('line_overlap_ratio', 0):.2%}")
        print(f"  分支覆盖重合度: {cov_result.get('branch_overlap_ratio', 0):.2%}")
        print(f"  GT增量行数: {cov_result.get('gt_increment_lines', 0)}")
        print(f"  User增量行数: {cov_result.get('user_increment_lines', 0)}")

        effort_result = result['evaluation']['modification_effort']
        print(f"\n[改动量]")
        print(f"  修改的测试方法数: {effort_result.get('total_methods', 0)}")
        print(f"  改动量得分: {effort_result.get('average_score', 0):.2%} (越高越好，表示改动越少)")

        # 综合得分
        scores = result.get('scores', {})
        print(f"\n[综合得分]")
        print(f"  覆盖增量重合度: {scores.get('coverage_overlap', 0):.2%}")
        print(f"  改动量得分: {scores.get('modification_score', 0):.2%}")
        print(f"  最终得分: {scores.get('overall', 0):.2%} (0.6×覆盖 + 0.4×改动量)")

    else:
        print(f"✗ 评估失败: {result.get('error')}")

    # 保存结果
    if args.output:
        output_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

        # 转换set为list
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
        print(f"\n结果已保存到: {output_path}")

    return 0 if result['success'] else 1


def cmd_run_batch(args, logger):
    """批量执行评估"""
    # 读取任务文件
    with open(args.input, 'r') as f:
        data = json.load(f)

    tasks = data.get('tasks', [])
    if not tasks:
        logger.error("任务文件中没有任务")
        return 1

    # 获取项目路径
    project_path = args.project
    if not project_path:
        # 从第一个任务获取
        project_path = tasks[0].get('project')

    if not project_path or not os.path.exists(project_path):
        logger.error("无法确定项目路径")
        return 1

    # 创建评估器
    orchestrator = EvaluationOrchestrator(project_path)

    # 执行批量评估
    results = orchestrator.run_batch_evaluation(tasks, args.output)

    # 输出统计
    print("\n" + "=" * 60)
    print("批量评估完成")
    print("=" * 60)
    print(f"总任务数: {results['metadata']['total_tasks']}")
    print(f"成功: {results['metadata']['successful']}")
    print(f"失败: {results['metadata']['failed']}")
    print(f"\n结果已保存到: {args.output}")

    return 0


def cmd_report(args, logger):
    """生成评估报告"""
    with open(args.input, 'r') as f:
        data = json.load(f)

    results = data.get('results', [])

    print("\n" + "=" * 60)
    print("评估报告")
    print("=" * 60)

    if data.get('metadata'):
        meta = data['metadata']
        print(f"评估时间: {meta.get('evaluation_time')}")
        print(f"总任务数: {meta.get('total_tasks')}")
        print(f"成功: {meta.get('successful')}")
        print(f"失败: {meta.get('failed')}")

    print("\n详细结果:")
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
            # 新版字段为 average_score；保留对旧字段 average_jaccard 的兼容
            jaccard = effort_result.get('average_score', effort_result.get('average_jaccard', 0))

            print(f"{gt_commit}: 编译{compile_ok} 测试{test_ok} "
                  f"覆盖重合={line_overlap:.0%} Jaccard={jaccard:.0%}")
        else:
            error = r.get('error', 'Unknown error')[:50]
            print(f"{gt_commit}: ✗ {error}")

    return 0


def cmd_cleanup(args, logger):
    """清理worktree"""
    if args.all:
        if not args.project:
            logger.error("使用 --all 时需要指定 --project")
            return 1

        manager = WorktreeManager(args.project)
        count = manager.cleanup_all_worktrees()
        print(f"清理了 {count} 个评估worktree")

    elif args.worktree:
        # 获取项目路径
        from git import Repo
        worktree_repo = Repo(args.worktree)
        git_common_dir = worktree_repo.git.rev_parse('--git-common-dir')
        project_path = os.path.dirname(git_common_dir)

        manager = WorktreeManager(project_path)
        if manager.cleanup_worktree(args.worktree):
            print(f"已清理: {args.worktree}")
        else:
            logger.error("清理失败")
            return 1

    else:
        logger.error("请指定 --worktree 或 --all")
        return 1

    return 0


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    if not args.command:
        print("请指定命令。使用 --help 查看帮助。")
        return 1

    # 执行命令
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
        logger.error(f"未知命令: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
