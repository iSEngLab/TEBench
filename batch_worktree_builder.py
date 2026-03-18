#!/usr/bin/env python3
"""
批量Worktree构建工具
从commit_summary.xlsx读取commit列表，批量创建worktree，并维护Excel记录表

命令示例:
---------
# 构建commons-csv项目的type1和type2类型worktree
python batch_worktree_builder.py --verbose build \
  -i ../commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/dataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/dataset/commons-csv \
  --projects commons-csv \
  --types type1 type2

# 查看统计信息
python batch_worktree_builder.py stats -o /Users/mac/Desktop/TestUpdate/dataset/worktree_records.xlsx

# 更新评估结果
python batch_worktree_builder.py update -o /Users/mac/Desktop/TestUpdate/dataset/worktree_records.xlsx \
  --task-id 1 --results eval_result.json
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Any

import pandas as pd
from git import Repo

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, AnalysisConfig
from utils.logger import setup_logger, get_logger
from evaluation import WorktreeManager


# 项目路径映射（项目名 -> 本地仓库路径）
_BASE = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
PROJECT_PATHS = {
    "closure-compiler": f"{_BASE}/closure-compiler",
    "commons-cli": f"{_BASE}/commons-cli",
    "commons-codec": f"{_BASE}/commons-codec",
    "commons-collections": f"{_BASE}/commons-collections",
    "commons-compress": f"{_BASE}/commons-compress",
    "commons-csv": f"{_BASE}/commons-csv",
    "commons-jxpath": f"{_BASE}/commons-jxpath",
    "commons-lang": f"{_BASE}/commons-lang",
    "commons-math": f"{_BASE}/commons-math",
    "gson": f"{_BASE}/gson",
    "jackson-core": f"{_BASE}/jackson-core",
    "jackson-databind": f"{_BASE}/jackson-databind",
    "jackson-dataformat-xml": f"{_BASE}/jackson-dataformat-xml",
    "jfreechart": f"{_BASE}/jfreechart",
    "joda-time": f"{_BASE}/joda-time",
    "jsoup": f"{_BASE}/jsoup",
    "mockito": f"{_BASE}/mockito",
}

# 输出Excel的列定义
OUTPUT_COLUMNS = [
    "task_id",           # 任务ID
    "project",           # 项目名
    "project_path",      # 项目原路径
    "worktree_path",     # worktree路径
    "v_minus_1_commit",  # V-1 commit (parent)
    "v_0_5_commit",      # V-0.5 commit (生成的)
    "v_0_commit",        # V0 commit (GT)
    "type",              # commit类型 (type1/type2等)
    "status",            # 状态: pending/ready/evaluated/failed
    "created_at",        # 创建时间
    "error_message",     # 错误信息
    # 评估指标预留列
    "compile_success",   # 编译是否成功
    "test_success",      # 测试是否成功
    "line_coverage_overlap",    # 行覆盖重合度
    "branch_coverage_overlap",  # 分支覆盖重合度
    "modification_score",       # 改动量得分
    "overall_score",            # 综合得分
    "evaluated_at",             # 评估时间
    "notes",                    # 备注
]


class BatchWorktreeBuilder:
    """批量Worktree构建器"""

    def __init__(self,
                 input_excel: str,
                 output_excel: str,
                 eval_dir: str = None,
                 project_paths: Dict[str, str] = None):
        """
        初始化

        Args:
            input_excel: 输入的commit_summary.xlsx路径
            output_excel: 输出的记录表路径
            eval_dir: worktree输出目录
            project_paths: 项目路径映射
        """
        self.input_excel = input_excel
        self.output_excel = output_excel
        self.eval_dir = eval_dir or WorktreeManager.DEFAULT_EVAL_DIR
        self.project_paths = project_paths or PROJECT_PATHS

        self.logger = get_logger()

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_excel) or '.', exist_ok=True)
        os.makedirs(self.eval_dir, exist_ok=True)

    def load_input_commits(self) -> pd.DataFrame:
        """加载输入的commit列表（支持.xlsx和.csv）"""
        if self.input_excel.endswith('.csv'):
            df = pd.read_csv(self.input_excel)
        else:
            df = pd.read_excel(self.input_excel)
        self.logger.info(f"加载了 {len(df)} 条commit记录")
        return df

    def load_or_create_output(self) -> pd.DataFrame:
        """加载或创建输出记录表（支持.xlsx和.csv）"""
        if os.path.exists(self.output_excel):
            if self.output_excel.endswith('.csv'):
                df = pd.read_csv(self.output_excel)
            else:
                df = pd.read_excel(self.output_excel)
            self.logger.info(f"加载已有记录表，包含 {len(df)} 条记录")
        else:
            df = pd.DataFrame(columns=OUTPUT_COLUMNS)
            self.logger.info("创建新的记录表")
        return df

    def save_output(self, df: pd.DataFrame):
        """保存输出记录表（支持.xlsx和.csv，同时保存两种格式）"""
        # 保存主文件
        if self.output_excel.endswith('.csv'):
            df.to_csv(self.output_excel, index=False)
        else:
            df.to_excel(self.output_excel, index=False)
        self.logger.info(f"保存记录表到 {self.output_excel}")

        # 同时保存另一种格式
        if self.output_excel.endswith('.xlsx'):
            csv_path = self.output_excel.replace('.xlsx', '.csv')
            df.to_csv(csv_path, index=False)
            self.logger.debug(f"同步保存CSV到 {csv_path}")
        elif self.output_excel.endswith('.csv'):
            xlsx_path = self.output_excel.replace('.csv', '.xlsx')
            df.to_excel(xlsx_path, index=False)
            self.logger.debug(f"同步保存Excel到 {xlsx_path}")

    def get_project_path(self, project_name: str) -> Optional[str]:
        """获取项目路径"""
        path = self.project_paths.get(project_name)
        if path and os.path.exists(path):
            return path
        return None

    def build_single_worktree(self,
                               project: str,
                               commit_id: str,
                               commit_type: str) -> Dict[str, Any]:
        """
        构建单个worktree

        Args:
            project: 项目名
            commit_id: commit hash
            commit_type: commit类型

        Returns:
            dict: 构建结果
        """
        result = {
            "project": project,
            "v_0_commit": commit_id[:8],
            "type": commit_type,
            "status": "failed",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_message": None,
        }

        # 获取项目路径
        project_path = self.get_project_path(project)
        if not project_path:
            result["error_message"] = f"项目路径未配置或不存在: {project}"
            return result

        result["project_path"] = project_path

        try:
            # 创建WorktreeManager
            manager = WorktreeManager(project_path, self.eval_dir)

            # 获取缓存目录
            cache_dir = os.path.join(AnalysisConfig.CACHE_DIR, project)

            # 准备worktree
            wt_result = manager.prepare_evaluation_worktree(commit_id, cache_dir)

            if wt_result['success']:
                result["status"] = "ready"
                result["worktree_path"] = wt_result['worktree_path']
                result["v_minus_1_commit"] = wt_result['parent_commit'][:8] if wt_result['parent_commit'] else None
                result["v_0_5_commit"] = wt_result['v05_commit'][:8] if wt_result['v05_commit'] else None
                result["task_id"] = wt_result.get('task_id')
            else:
                result["error_message"] = wt_result.get('error', 'Unknown error')

        except Exception as e:
            result["error_message"] = str(e)
            self.logger.error(f"构建worktree失败 [{project}/{commit_id[:8]}]: {e}")

        return result

    def build_batch(self,
                    projects: List[str] = None,
                    types: List[str] = None,
                    limit: int = None,
                    skip_existing: bool = True) -> pd.DataFrame:
        """
        批量构建worktree

        Args:
            projects: 要处理的项目列表（None表示全部）
            types: 要处理的类型列表（None表示全部）
            limit: 最大处理数量
            skip_existing: 是否跳过已存在的记录

        Returns:
            DataFrame: 更新后的记录表
        """
        # 加载数据
        input_df = self.load_input_commits()
        output_df = self.load_or_create_output()

        # 过滤
        filtered_df = input_df.copy()
        if projects:
            filtered_df = filtered_df[filtered_df['Project'].isin(projects)]
        if types:
            filtered_df = filtered_df[filtered_df['Type'].isin(types)]

        self.logger.info(f"过滤后待处理: {len(filtered_df)} 条")

        # 获取已处理的commit
        existing_commits = set()
        if skip_existing and len(output_df) > 0:
            existing_commits = set(output_df['v_0_commit'].dropna().astype(str))

        # 处理
        processed = 0
        new_records = []

        for idx, row in filtered_df.iterrows():
            project = row['Project']
            commit_id = str(row['CommitID'])
            commit_type = row['Type']

            # 跳过已存在的（比较前8位）
            if commit_id[:8] in existing_commits:
                self.logger.debug(f"跳过已存在: {project}/{commit_id[:8]}")
                continue

            # 检查限制
            if limit and processed >= limit:
                self.logger.info(f"达到处理限制: {limit}")
                break

            # 构建worktree
            self.logger.info(f"[{processed+1}] 处理 {project}/{commit_id[:8]} ({commit_type})")
            result = self.build_single_worktree(project, commit_id, commit_type)
            new_records.append(result)

            processed += 1

            # 定期保存
            if processed % 10 == 0:
                temp_df = pd.concat([output_df, pd.DataFrame(new_records)], ignore_index=True)
                self.save_output(temp_df)
                self.logger.info(f"已处理 {processed} 条，中间保存")

        # 合并结果
        if new_records:
            output_df = pd.concat([output_df, pd.DataFrame(new_records)], ignore_index=True)

        # 最终保存
        self.save_output(output_df)

        # 统计
        success_count = len([r for r in new_records if r['status'] == 'ready'])
        fail_count = len([r for r in new_records if r['status'] == 'failed'])
        self.logger.info(f"\n处理完成: 成功 {success_count}, 失败 {fail_count}")

        return output_df

    def clean_project_branches(self,
                               projects: List[str] = None,
                               eval_dir: str = None,
                               dry_run: bool = False) -> Dict[str, Any]:
        """
        清理指定项目中由本工具创建的 eval/* 分支及对应的 worktree 目录。

        分支命名规则: eval/<project>-task_NNN
        Worktree 目录规则: <eval_dir>/<project>-task_NNN_eval

        Args:
            projects: 要清理的项目列表（None 表示全部已配置项目）
            eval_dir: worktree 输出目录（None 使用实例默认值）
            dry_run: 仅打印，不实际删除

        Returns:
            dict: { project: { 'branches': [...], 'worktrees': [...], 'errors': [...] } }
        """
        import re
        from git import Repo, GitCommandError

        eval_dir = eval_dir or self.eval_dir
        target_projects = projects or list(self.project_paths.keys())
        summary = {}

        for project in target_projects:
            repo_path = self.get_project_path(project)
            if not repo_path:
                self.logger.warning(f"[{project}] 路径未配置或不存在，跳过")
                continue

            info = {'branches': [], 'worktrees': [], 'errors': []}
            summary[project] = info
            pattern = re.compile(rf'^eval/{re.escape(project)}-task_(\d+)$')

            try:
                repo = Repo(repo_path)
            except Exception as e:
                info['errors'].append(f"打开仓库失败: {e}")
                continue

            # 1. 找出所有匹配分支
            try:
                all_branches = repo.git.branch().split('\n')
            except Exception as e:
                info['errors'].append(f"列出分支失败: {e}")
                continue

            matched_branches = []
            for b in all_branches:
                b = b.strip().lstrip('* ')
                if pattern.match(b):
                    matched_branches.append(b)

            if not matched_branches:
                self.logger.info(f"[{project}] 未发现 eval/* 分支，无需清理")
                continue

            self.logger.info(f"[{project}] 发现 {len(matched_branches)} 个分支待清理")

            # 2. 获取当前所有 worktree 信息（路径 -> 分支 的映射）
            worktree_branch_map = {}  # branch_name -> worktree_path
            try:
                wt_output = repo.git.worktree('list', '--porcelain')
                current_wt_path = None
                current_wt_branch = None
                for line in wt_output.splitlines():
                    if line.startswith('worktree '):
                        current_wt_path = line[len('worktree '):].strip()
                    elif line.startswith('branch '):
                        current_wt_branch = line[len('branch '):].strip()
                        # git 输出格式: refs/heads/eval/...
                        if current_wt_branch.startswith('refs/heads/'):
                            current_wt_branch = current_wt_branch[len('refs/heads/'):]
                        if current_wt_branch and current_wt_path:
                            worktree_branch_map[current_wt_branch] = current_wt_path
            except Exception as e:
                self.logger.debug(f"[{project}] 获取worktree列表失败: {e}")

            # 3. 逐个清理
            for branch in matched_branches:
                # 3a. 先移除关联的 worktree（必须在删除分支之前）
                wt_path = worktree_branch_map.get(branch)
                if not wt_path:
                    # 按命名规则推导目录
                    m = pattern.match(branch)
                    if m:
                        task_id = int(m.group(1))
                        wt_path = os.path.join(
                            eval_dir,
                            f"{project}-task_{task_id:03d}_eval"
                        )

                if wt_path and os.path.exists(wt_path):
                    if dry_run:
                        self.logger.info(f"  [dry-run] 删除 worktree: {wt_path}")
                    else:
                        try:
                            repo.git.worktree('remove', '--force', wt_path)
                            info['worktrees'].append(wt_path)
                            self.logger.info(f"  ✓ 删除 worktree: {wt_path}")
                        except Exception as e:
                            # worktree remove 失败时直接删目录
                            try:
                                import shutil
                                shutil.rmtree(wt_path, ignore_errors=True)
                                repo.git.worktree('prune')
                                info['worktrees'].append(wt_path)
                                self.logger.info(f"  ✓ 强制删除 worktree 目录: {wt_path}")
                            except Exception as e2:
                                info['errors'].append(f"删除worktree失败 {wt_path}: {e2}")
                                self.logger.warning(f"  ✗ 删除worktree失败: {e2}")

                # 3b. 删除分支
                if dry_run:
                    self.logger.info(f"  [dry-run] 删除分支: {branch}")
                else:
                    try:
                        repo.git.branch('-D', branch)
                        info['branches'].append(branch)
                        self.logger.info(f"  ✓ 删除分支: {branch}")
                    except GitCommandError as e:
                        info['errors'].append(f"删除分支失败 {branch}: {e}")
                        self.logger.warning(f"  ✗ 删除分支失败 {branch}: {e}")

            # 4. prune 残留引用
            if not dry_run:
                try:
                    repo.git.worktree('prune')
                except Exception:
                    pass

            self.logger.info(
                f"[{project}] 完成: 删除分支 {len(info['branches'])} 个，"
                f"worktree {len(info['worktrees'])} 个，"
                f"错误 {len(info['errors'])} 个"
            )

        return summary

    def update_evaluation_results(self,
                                   task_id: int = None,
                                   worktree_path: str = None,
                                   results: Dict[str, Any] = None):
        """
        更新评估结果到记录表

        Args:
            task_id: 任务ID
            worktree_path: worktree路径
            results: 评估结果字典
        """
        output_df = self.load_or_create_output()

        # 查找记录
        mask = None
        if task_id is not None:
            mask = output_df['task_id'] == task_id
        elif worktree_path:
            mask = output_df['worktree_path'] == worktree_path

        if mask is None or not mask.any():
            self.logger.warning("未找到匹配的记录")
            return

        # 更新评估结果
        idx = output_df[mask].index[0]

        if results:
            output_df.loc[idx, 'compile_success'] = results.get('compile_success')
            output_df.loc[idx, 'test_success'] = results.get('test_success')
            output_df.loc[idx, 'line_coverage_overlap'] = results.get('line_coverage_overlap')
            output_df.loc[idx, 'branch_coverage_overlap'] = results.get('branch_coverage_overlap')
            output_df.loc[idx, 'modification_score'] = results.get('modification_score')
            output_df.loc[idx, 'overall_score'] = results.get('overall_score')
            output_df.loc[idx, 'status'] = 'evaluated'
            output_df.loc[idx, 'evaluated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.save_output(output_df)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        output_df = self.load_or_create_output()

        stats = {
            "total": len(output_df),
            "by_status": output_df['status'].value_counts().to_dict(),
            "by_project": output_df['project'].value_counts().to_dict(),
            "by_type": output_df['type'].value_counts().to_dict(),
        }

        # 评估统计
        evaluated = output_df[output_df['status'] == 'evaluated']
        if len(evaluated) > 0:
            stats["evaluation"] = {
                "count": len(evaluated),
                "avg_line_coverage": evaluated['line_coverage_overlap'].mean(),
                "avg_branch_coverage": evaluated['branch_coverage_overlap'].mean(),
                "avg_modification_score": evaluated['modification_score'].mean(),
                "avg_overall_score": evaluated['overall_score'].mean(),
            }

        return stats


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='批量Worktree构建工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  # 构建所有commit的worktree
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx

  # 只处理特定项目
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --projects commons-csv commons-cli

  # 只处理特定类型
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --types type1

  # 限制处理数量
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --limit 10

  # 查看统计信息
  python batch_worktree_builder.py stats --output ./output/worktree_records.xlsx
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # build 命令
    build_parser = subparsers.add_parser('build', help='批量构建worktree')
    build_parser.add_argument('--input', '-i', type=str, required=True,
                              help='输入的commit_summary.xlsx路径')
    build_parser.add_argument('--output', '-o', type=str, required=True,
                              help='输出的记录表路径')
    build_parser.add_argument('--eval-dir', type=str,
                              help='worktree输出目录')
    build_parser.add_argument('--projects', '-p', nargs='+',
                              help='要处理的项目列表')
    build_parser.add_argument('--types', '-t', nargs='+',
                              help='要处理的类型列表')
    build_parser.add_argument('--limit', '-l', type=int,
                              help='最大处理数量')
    build_parser.add_argument('--no-skip', action='store_true',
                              help='不跳过已存在的记录')

    # stats 命令
    stats_parser = subparsers.add_parser('stats', help='查看统计信息')
    stats_parser.add_argument('--output', '-o', type=str, required=True,
                              help='记录表路径')

    # clean 命令
    clean_parser = subparsers.add_parser('clean', help='清理指定项目的 eval/* 分支和 worktree 目录')
    clean_parser.add_argument('--eval-dir', type=str,
                              help='worktree 输出目录（与 build 时保持一致）')
    clean_parser.add_argument('--projects', '-p', nargs='+',
                              help='要清理的项目列表（不填则清理全部已配置项目）')
    clean_parser.add_argument('--dry-run', action='store_true',
                              help='仅打印将要删除的内容，不实际执行')

    # update 命令
    update_parser = subparsers.add_parser('update', help='更新评估结果')
    update_parser.add_argument('--output', '-o', type=str, required=True,
                               help='记录表路径')
    update_parser.add_argument('--task-id', type=int,
                               help='任务ID')
    update_parser.add_argument('--worktree', type=str,
                               help='worktree路径')
    update_parser.add_argument('--results', type=str,
                               help='评估结果JSON文件')

    # 通用参数
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def cmd_build(args, logger):
    """执行批量构建"""
    builder = BatchWorktreeBuilder(
        input_excel=args.input,
        output_excel=args.output,
        eval_dir=args.eval_dir
    )

    builder.build_batch(
        projects=args.projects,
        types=args.types,
        limit=args.limit,
        skip_existing=not args.no_skip
    )

    return 0


def cmd_stats(args, logger):
    """显示统计信息"""
    builder = BatchWorktreeBuilder(
        input_excel="",  # 不需要输入
        output_excel=args.output
    )

    stats = builder.get_statistics()

    print("\n" + "=" * 60)
    print("Worktree构建统计")
    print("=" * 60)

    print(f"\n总记录数: {stats['total']}")

    print("\n按状态统计:")
    for status, count in stats.get('by_status', {}).items():
        print(f"  {status}: {count}")

    print("\n按项目统计:")
    for project, count in stats.get('by_project', {}).items():
        print(f"  {project}: {count}")

    print("\n按类型统计:")
    for type_, count in stats.get('by_type', {}).items():
        print(f"  {type_}: {count}")

    if 'evaluation' in stats:
        eval_stats = stats['evaluation']
        print(f"\n评估统计 ({eval_stats['count']} 条):")
        print(f"  平均行覆盖重合度: {eval_stats['avg_line_coverage']:.2%}")
        print(f"  平均分支覆盖重合度: {eval_stats['avg_branch_coverage']:.2%}")
        print(f"  平均改动量得分: {eval_stats['avg_modification_score']:.2%}")
        print(f"  平均综合得分: {eval_stats['avg_overall_score']:.2%}")

    return 0


def cmd_clean(args, logger):
    """清理 eval/* 分支和 worktree 目录"""
    builder = BatchWorktreeBuilder(
        input_excel="",
        output_excel="",
        eval_dir=getattr(args, 'eval_dir', None)
    )

    if getattr(args, 'dry_run', False):
        print("[dry-run 模式] 以下内容将被删除（不会实际执行）：")

    summary = builder.clean_project_branches(
        projects=args.projects,
        eval_dir=getattr(args, 'eval_dir', None),
        dry_run=getattr(args, 'dry_run', False)
    )

    print("\n" + "=" * 60)
    print("清理统计")
    print("=" * 60)
    total_branches = sum(len(v['branches']) for v in summary.values())
    total_wt = sum(len(v['worktrees']) for v in summary.values())
    total_err = sum(len(v['errors']) for v in summary.values())
    for project, info in summary.items():
        print(f"\n{project}:")
        print(f"  删除分支: {len(info['branches'])} 个")
        print(f"  删除worktree: {len(info['worktrees'])} 个")
        if info['errors']:
            for e in info['errors']:
                print(f"  ✗ {e}")
    print(f"\n合计: 分支 {total_branches} 个，worktree {total_wt} 个，错误 {total_err} 个")
    return 0


def cmd_update(args, logger):
    """更新评估结果"""
    builder = BatchWorktreeBuilder(
        input_excel="",
        output_excel=args.output
    )

    results = None
    if args.results:
        with open(args.results, 'r') as f:
            results = json.load(f)

    builder.update_evaluation_results(
        task_id=args.task_id,
        worktree_path=args.worktree,
        results=results
    )

    print("评估结果已更新")
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

    commands = {
        'build': cmd_build,
        'stats': cmd_stats,
        'update': cmd_update,
        'clean': cmd_clean,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        return cmd_func(args, logger)
    else:
        logger.error(f"未知命令: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
