#!/usr/bin/env python3
"""
Batch OpenCode Runner - 批量执行OpenCode进行过时测试用例识别和更新

功能:
1. 从worktree_records.xlsx读取待评估的worktree列表
2. 为每个worktree生成对应的prompt
3. 并行调用OpenCode执行测试更新任务
4. 记录执行结果和修改内容
5. 不提交修改，保留在worktree中供后续评估

使用示例:
---------
# 批量执行，并行度为2
python batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --status ready

# 只处理特定项目
python batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --projects commons-csv gson

# 只处理特定类型
python batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --types type1 type2

# 限制处理数量（用于测试）
python batch_opencode_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/opencode_results \
  --workers 2 \
  --limit 5
"""

import os
import sys
import json
import argparse
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# 添加项目根目录到路径
# baseline/opencode/scripts/batch_opencode_runner.py -> TUBench/
script_dir = os.path.dirname(os.path.abspath(__file__))  # scripts/
opencode_dir = os.path.dirname(script_dir)  # opencode/
baseline_dir = os.path.dirname(opencode_dir)  # baseline/
project_root = os.path.dirname(baseline_dir)  # TUBench/
sys.path.insert(0, project_root)

from utils.logger import setup_logger, get_logger
from baseline.opencode.scripts.prompts import get_prompt_for_type, format_task_prompt

# 尝试导入pandas
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Warning: pandas not installed. Install with: pip install pandas openpyxl")


class OpenCodeRunner:
    """OpenCode批量执行器"""

    def __init__(self,
                 input_excel: str,
                 output_dir: str,
                 opencode_path: str = None,
                 workers: int = 2,
                 timeout: int = 1800):
        """
        初始化

        Args:
            input_excel: worktree_records.xlsx路径
            output_dir: 输出目录
            opencode_path: opencode可执行文件路径
            workers: 并行worker数量
            timeout: 单个任务超时时间（秒）
        """
        if not HAS_PANDAS:
            raise RuntimeError("pandas is required. Install with: pip install pandas openpyxl")

        # 先初始化logger
        self.logger = get_logger()

        self.input_excel = input_excel
        self.output_dir = output_dir
        self.opencode_path = opencode_path or self._find_opencode()
        self.workers = workers
        self.timeout = timeout

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'logs'), exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'prompts'), exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'results'), exist_ok=True)

    def _find_opencode(self) -> str:
        """查找opencode可执行文件"""
        # 尝试常见路径
        candidates = [
            '/Users/mac/.opencode/bin/opencode',
            os.path.expanduser('~/.opencode/bin/opencode'),
            'opencode',  # 在PATH中
        ]

        for path in candidates:
            if os.path.exists(path) or self._check_command_exists(path):
                self.logger.info(f"Found opencode at: {path}")
                return path

        raise RuntimeError("opencode not found. Please install or specify path with --opencode-path")

    def _check_command_exists(self, cmd: str) -> bool:
        """检查命令是否存在"""
        try:
            subprocess.run(['which', cmd], capture_output=True, check=True)
            return True
        except:
            return False

    def load_worktree_records(self,
                              status_filter: List[str] = None,
                              project_filter: List[str] = None,
                              type_filter: List[str] = None) -> pd.DataFrame:
        """
        加载worktree记录

        Args:
            status_filter: 状态过滤（如 ['ready']）
            project_filter: 项目过滤
            type_filter: 类型过滤

        Returns:
            DataFrame: 过滤后的记录
        """
        df = pd.read_excel(self.input_excel)
        self.logger.info(f"Loaded {len(df)} worktree records")

        # 应用过滤
        if status_filter:
            df = df[df['status'].isin(status_filter)]
            self.logger.info(f"Filtered by status {status_filter}: {len(df)} records")

        if project_filter:
            df = df[df['project'].isin(project_filter)]
            self.logger.info(f"Filtered by project {project_filter}: {len(df)} records")

        if type_filter:
            df = df[df['type'].isin(type_filter)]
            self.logger.info(f"Filtered by type {type_filter}: {len(df)} records")

        return df

    def generate_prompt(self, record: Dict[str, Any]) -> str:
        """
        为单个记录生成prompt

        Args:
            record: worktree记录

        Returns:
            str: 生成的prompt

        Note:
            不暴露V0 (Ground Truth) commit信息，防止AI通过git show/checkout
            直接获取答案。只提供当前worktree的状态说明。
        """
        commit_type = record.get('type', 'unknown')
        project_name = record.get('project', 'unknown')

        # 添加额外上下文 - 不包含V0 commit信息
        additional_context = f"""## Task Description
The source code in this project has been updated (the current HEAD contains the changes).
The test code has NOT been updated and may now be outdated.
Your task is to first identify which tests are outdated, then update them accordingly."""

        prompt = format_task_prompt(
            commit_type=commit_type,
            project_name=project_name,
            additional_context=additional_context
        )

        return prompt

    def save_prompt(self, task_id: int, prompt: str) -> str:
        """保存prompt到文件"""
        prompt_file = os.path.join(self.output_dir, 'prompts', f'task_{task_id:03d}_prompt.txt')
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        return prompt_file

    def run_opencode_task(self,
                          task_id: int,
                          worktree_path: str,
                          prompt: str) -> Dict[str, Any]:
        """
        执行单个OpenCode任务

        Args:
            task_id: 任务ID
            worktree_path: worktree路径
            prompt: 任务prompt

        Returns:
            dict: 执行结果
        """
        result = {
            'task_id': task_id,
            'worktree_path': worktree_path,
            'success': False,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'duration': None,
            'exit_code': None,
            'stdout': None,
            'stderr': None,
            'error': None,
            'modified_files': [],
        }

        log_file = os.path.join(self.output_dir, 'logs', f'task_{task_id:03d}.log')
        result_file = os.path.join(self.output_dir, 'results', f'task_{task_id:03d}_result.json')

        try:
            start_time = time.time()

            # 保存prompt
            prompt_file = self.save_prompt(task_id, prompt)
            self.logger.info(f"[Task {task_id}] Saved prompt to {prompt_file}")

            # 构建OpenCode命令
            # OpenCode使用: opencode run <message> --dir <directory>
            cmd = [
                self.opencode_path,
                'run',
                prompt,
                '--dir', worktree_path,
            ]

            self.logger.info(f"[Task {task_id}] Running OpenCode in {worktree_path}")
            self.logger.debug(f"[Task {task_id}] Command: {' '.join(cmd)}")

            # 执行OpenCode
            with open(log_file, 'w') as log_f:
                process = subprocess.run(
                    cmd,
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )

                # 记录输出
                log_f.write(f"=== STDOUT ===\n{process.stdout}\n")
                log_f.write(f"=== STDERR ===\n{process.stderr}\n")

                result['exit_code'] = process.returncode
                result['stdout'] = process.stdout
                result['stderr'] = process.stderr

            end_time = time.time()
            result['end_time'] = datetime.now().isoformat()
            result['duration'] = end_time - start_time

            # 检查是否成功
            if process.returncode == 0:
                result['success'] = True
                self.logger.info(f"[Task {task_id}] Completed successfully in {result['duration']:.1f}s")

                # 检测修改的文件
                modified_files = self._detect_modified_files(worktree_path)
                result['modified_files'] = modified_files
                self.logger.info(f"[Task {task_id}] Modified {len(modified_files)} files")
            else:
                result['error'] = f"OpenCode exited with code {process.returncode}"
                self.logger.warning(f"[Task {task_id}] Failed with exit code {process.returncode}")

        except subprocess.TimeoutExpired:
            result['error'] = f"Timeout after {self.timeout}s"
            result['end_time'] = datetime.now().isoformat()
            self.logger.error(f"[Task {task_id}] Timeout after {self.timeout}s")

        except Exception as e:
            result['error'] = str(e)
            result['end_time'] = datetime.now().isoformat()
            self.logger.error(f"[Task {task_id}] Error: {e}", exc_info=True)

        # 保存结果
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return result

    def _detect_modified_files(self, worktree_path: str) -> List[str]:
        """
        检测worktree中修改的文件

        Args:
            worktree_path: worktree路径

        Returns:
            list: 修改的文件列表
        """
        try:
            # 使用git status检测修改
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True
            )

            modified_files = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    # 格式: " M file.java" 或 "M  file.java"
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        modified_files.append(parts[1])

            return modified_files

        except Exception as e:
            self.logger.warning(f"Failed to detect modified files: {e}")
            return []

    def run_batch(self,
                  status_filter: List[str] = None,
                  project_filter: List[str] = None,
                  type_filter: List[str] = None,
                  limit: int = None) -> List[Dict[str, Any]]:
        """
        批量执行OpenCode任务

        Args:
            status_filter: 状态过滤
            project_filter: 项目过滤
            type_filter: 类型过滤
            limit: 最大处理数量

        Returns:
            list: 所有任务的执行结果
        """
        # 加载记录
        df = self.load_worktree_records(
            status_filter=status_filter,
            project_filter=project_filter,
            type_filter=type_filter
        )

        if limit:
            df = df.head(limit)
            self.logger.info(f"Limited to {limit} records")

        if len(df) == 0:
            self.logger.warning("No records to process")
            return []

        self.logger.info(f"Processing {len(df)} records with {self.workers} workers")

        # 准备任务
        tasks = []
        for idx, row in df.iterrows():
            task_id = row.get('task_id', idx + 1)
            worktree_path = row['worktree_path']
            record = row.to_dict()

            # 生成prompt
            prompt = self.generate_prompt(record)

            tasks.append({
                'task_id': task_id,
                'worktree_path': worktree_path,
                'prompt': prompt,
                'record': record
            })

        # 并行执行
        results = []
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    run_opencode_task_worker,
                    task['task_id'],
                    task['worktree_path'],
                    task['prompt'],
                    self.opencode_path,
                    self.output_dir,
                    self.timeout
                ): task
                for task in tasks
            }

            completed = 0
            for future in as_completed(futures):
                task = futures[future]
                completed += 1

                try:
                    result = future.result()
                    results.append(result)

                    status = "✓" if result['success'] else "✗"
                    self.logger.info(
                        f"[{completed}/{len(tasks)}] Task {result['task_id']} {status} "
                        f"({result.get('duration', 0):.1f}s)"
                    )

                except Exception as e:
                    self.logger.error(f"Task {task['task_id']} failed: {e}")
                    results.append({
                        'task_id': task['task_id'],
                        'success': False,
                        'error': str(e)
                    })

        # 生成汇总报告
        self._generate_summary_report(results)

        return results

    def _generate_summary_report(self, results: List[Dict[str, Any]]):
        """生成汇总报告"""
        summary_file = os.path.join(self.output_dir, 'summary.json')

        summary = {
            'total': len(results),
            'successful': sum(1 for r in results if r.get('success')),
            'failed': sum(1 for r in results if not r.get('success')),
            'total_duration': sum(r.get('duration', 0) for r in results),
            'avg_duration': sum(r.get('duration', 0) for r in results) / len(results) if results else 0,
            'timestamp': datetime.now().isoformat(),
            'results': results
        }

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.logger.info(f"\n{'='*60}")
        self.logger.info("Batch Execution Summary")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Total: {summary['total']}")
        self.logger.info(f"Successful: {summary['successful']}")
        self.logger.info(f"Failed: {summary['failed']}")
        self.logger.info(f"Total Duration: {summary['total_duration']:.1f}s")
        self.logger.info(f"Avg Duration: {summary['avg_duration']:.1f}s")
        self.logger.info(f"\nSummary saved to: {summary_file}")


def run_opencode_task_worker(task_id: int,
                              worktree_path: str,
                              prompt: str,
                              opencode_path: str,
                              output_dir: str,
                              timeout: int) -> Dict[str, Any]:
    """
    Worker函数：在独立进程中执行OpenCode任务

    Args:
        task_id: 任务ID
        worktree_path: worktree路径
        prompt: 任务prompt
        opencode_path: opencode路径
        output_dir: 输出目录
        timeout: 超时时间

    Returns:
        dict: 执行结果
    """
    # 在worker进程中重新创建runner（只用于执行单个任务）
    runner = OpenCodeRunner(
        input_excel="",  # 不需要
        output_dir=output_dir,
        opencode_path=opencode_path,
        timeout=timeout
    )

    return runner.run_opencode_task(task_id, worktree_path, prompt)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Batch OpenCode Runner - 批量执行OpenCode进行测试更新',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='worktree_records.xlsx路径')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='输出目录')
    parser.add_argument('--opencode-path', type=str,
                        help='opencode可执行文件路径（默认自动查找）')

    parser.add_argument('--workers', '-w', type=int, default=2,
                        help='并行worker数量（默认: 2）')
    parser.add_argument('--timeout', '-t', type=int, default=1800,
                        help='单个任务超时时间（秒，默认: 1800）')

    parser.add_argument('--status', nargs='+',
                        help='状态过滤（如: ready）')
    parser.add_argument('--projects', '-p', nargs='+',
                        help='项目过滤')
    parser.add_argument('--types', nargs='+',
                        help='类型过滤（如: type1 type2）')
    parser.add_argument('--limit', '-l', type=int,
                        help='最大处理数量（用于测试）')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='详细日志输出')

    return parser.parse_args()


def main():
    """主函数"""
    args = parse_args()

    # 设置日志
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("="*60)
    logger.info("Batch OpenCode Runner")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # 创建runner
        runner = OpenCodeRunner(
            input_excel=args.input,
            output_dir=args.output,
            opencode_path=args.opencode_path,
            workers=args.workers,
            timeout=args.timeout
        )

        # 执行批量任务
        results = runner.run_batch(
            status_filter=args.status,
            project_filter=args.projects,
            type_filter=args.types,
            limit=args.limit
        )

        # 输出结果
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count

        logger.info(f"\nCompleted: {success_count} successful, {fail_count} failed")

        return 0 if fail_count == 0 else 1

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
