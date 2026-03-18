#!/usr/bin/env python3
"""
Batch Claude Code Runner - 批量执行Claude Code进行过时测试识别和更新

Claude Code CLI 命令:
  claude -p "<prompt>" --dangerously-skip-permissions

需要在worktree目录下执行（cd进去），Claude Code会自动以当前目录为工作目录。

使用示例:
---------
# 批量执行
python baseline/claude-code/scripts/batch_claude_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/results \
  --workers 2 --status ready

# 只处理特定项目
python baseline/claude-code/scripts/batch_claude_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/results \
  --projects commons-csv --limit 5

# 指定模型
python baseline/claude-code/scripts/batch_claude_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/claude-code/results \
  --model claude-sonnet-4-20250514
"""

import os
import sys
import json
import argparse
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Any
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OPENCODE_DIR = os.path.dirname(SCRIPT_DIR)
BASELINE_DIR = os.path.dirname(OPENCODE_DIR)
PROJECT_ROOT = os.path.dirname(BASELINE_DIR)
sys.path.insert(0, PROJECT_ROOT)

from utils.logger import setup_logger, get_logger
# prompts.py is co-located in the same scripts/ directory
sys.path.insert(0, SCRIPT_DIR)
from prompts import get_prompt_for_type, format_task_prompt


def detect_modified_files(worktree_path: str) -> List[str]:
    """检测worktree中修改的文件"""
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=worktree_path,
            capture_output=True, text=True, check=True
        )
        files = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1])
        return files
    except Exception:
        return []


def run_claude_task(task_id: int,
                    worktree_path: str,
                    prompt: str,
                    claude_path: str,
                    output_dir: str,
                    timeout: int,
                    model: str = None) -> Dict[str, Any]:
    """
    在独立进程中执行单个Claude Code任务

    Claude Code 使用: claude -p "<prompt>" --dangerously-skip-permissions
    需要cd到worktree目录执行
    """
    result = {
        'task_id': task_id,
        'worktree_path': worktree_path,
        'agent': 'claude-code',
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

    log_file = os.path.join(output_dir, 'logs', f'task_{task_id:03d}.log')
    result_file = os.path.join(output_dir, 'results', f'task_{task_id:03d}_result.json')
    prompt_file = os.path.join(output_dir, 'prompts', f'task_{task_id:03d}_prompt.txt')

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    os.makedirs(os.path.dirname(prompt_file), exist_ok=True)

    # 保存prompt
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    try:
        start_time = time.time()

        # 构建Claude Code命令
        # claude -p "<prompt>" --dangerously-skip-permissions
        cmd = [claude_path, '-p', prompt, '--dangerously-skip-permissions']
        if model:
            cmd.extend(['--model', model])

        # 在worktree目录下执行
        process = subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        end_time = time.time()
        result['exit_code'] = process.returncode
        result['stdout'] = process.stdout
        result['stderr'] = process.stderr
        result['end_time'] = datetime.now().isoformat()
        result['duration'] = end_time - start_time

        # 写日志
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== COMMAND ===\n{' '.join(cmd)}\n\n")
            f.write(f"=== CWD ===\n{worktree_path}\n\n")
            f.write(f"=== EXIT CODE ===\n{process.returncode}\n\n")
            f.write(f"=== STDOUT ===\n{process.stdout}\n\n")
            f.write(f"=== STDERR ===\n{process.stderr}\n")

        if process.returncode == 0:
            result['success'] = True
            result['modified_files'] = detect_modified_files(worktree_path)
        else:
            result['error'] = f"claude exited with code {process.returncode}"

    except subprocess.TimeoutExpired:
        result['error'] = f"Timeout after {timeout}s"
        result['end_time'] = datetime.now().isoformat()
    except Exception as e:
        result['error'] = str(e)
        result['end_time'] = datetime.now().isoformat()

    # 保存结果
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


class ClaudeCodeRunner:
    """Claude Code 批量执行器"""

    def __init__(self, input_csv: str, output_dir: str,
                 claude_path: str = None, workers: int = 2,
                 timeout: int = 1800, model: str = None):
        self.input_csv = input_csv
        self.output_dir = output_dir
        self.claude_path = claude_path or self._find_claude()
        self.workers = workers
        self.timeout = timeout
        self.model = model
        self.logger = get_logger()

        os.makedirs(output_dir, exist_ok=True)
        for sub in ['logs', 'prompts', 'results']:
            os.makedirs(os.path.join(output_dir, sub), exist_ok=True)

    def _find_claude(self) -> str:
        for path in ['/opt/homebrew/bin/claude', 'claude']:
            try:
                subprocess.run(['which', path], capture_output=True, check=True)
                return path
            except Exception:
                if os.path.exists(path):
                    return path
        raise RuntimeError("claude not found. Install Claude Code CLI first.")

    def load_records(self, status_filter=None, project_filter=None,
                     type_filter=None) -> pd.DataFrame:
        df = pd.read_csv(self.input_csv)
        if status_filter:
            df = df[df['status'].isin(status_filter)]
        if project_filter:
            df = df[df['project'].isin(project_filter)]
        if type_filter:
            df = df[df['type'].isin(type_filter)]
        return df

    def generate_prompt(self, record: Dict[str, Any]) -> str:
        commit_type = record.get('type', 'unknown')
        project_name = record.get('project', 'unknown')
        additional_context = (
            "## Task Description\n"
            "The source code in this project has been updated (the current HEAD contains the changes).\n"
            "The test code has NOT been updated and may now be outdated.\n"
            "Your task is to first identify which tests are outdated, then update them accordingly."
        )
        return format_task_prompt(commit_type, project_name, additional_context)

    def _is_task_completed(self, task_id: int) -> bool:
        """检查任务是否已成功完成（用于断点续传）"""
        result_file = os.path.join(self.output_dir, 'results', f'task_{task_id:03d}_result.json')
        if not os.path.exists(result_file):
            return False
        try:
            with open(result_file, 'r') as f:
                r = json.load(f)
            return r.get('success', False)
        except Exception:
            return False

    def _load_completed_results(self) -> List[Dict[str, Any]]:
        """加载所有已完成的结果（用于汇总）"""
        results = []
        results_dir = os.path.join(self.output_dir, 'results')
        if not os.path.exists(results_dir):
            return results
        for fname in os.listdir(results_dir):
            if fname.endswith('_result.json'):
                try:
                    with open(os.path.join(results_dir, fname), 'r') as f:
                        results.append(json.load(f))
                except Exception:
                    pass
        return results

    def run_batch(self, status_filter=None, project_filter=None,
                  type_filter=None, limit=None,
                  resume=True, retry_failed=False) -> List[Dict[str, Any]]:
        """
        批量执行任务

        Args:
            resume: 跳过已成功完成的任务（断点续传，默认开启）
            retry_failed: 重试之前失败的任务
        """
        df = self.load_records(status_filter, project_filter, type_filter)
        if limit:
            df = df.head(limit)

        if len(df) == 0:
            self.logger.warning("No records to process")
            return []

        # 构建任务列表，支持断点续传
        tasks = []
        skipped = 0
        for _, row in df.iterrows():
            record = row.to_dict()
            task_id = record.get('task_id', 0)

            if resume and self._is_task_completed(task_id):
                skipped += 1
                continue

            # 如果不retry_failed，也跳过已有结果（无论成功失败）的任务
            if not retry_failed and not resume:
                result_file = os.path.join(self.output_dir, 'results', f'task_{task_id:03d}_result.json')
                if os.path.exists(result_file):
                    skipped += 1
                    continue

            tasks.append({
                'task_id': task_id,
                'worktree_path': record['worktree_path'],
                'prompt': self.generate_prompt(record),
            })

        if skipped > 0:
            self.logger.info(f"跳过 {skipped} 个已完成的任务（断点续传）")

        if len(tasks) == 0:
            self.logger.info("所有任务已完成，无需执行")
            all_results = self._load_completed_results()
            self._save_summary(all_results)
            return all_results

        self.logger.info(f"待执行: {len(tasks)} 个任务, workers={self.workers}")

        results = []
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    run_claude_task,
                    t['task_id'], t['worktree_path'], t['prompt'],
                    self.claude_path, self.output_dir, self.timeout,
                    self.model,
                ): t for t in tasks
            }

            done = 0
            for future in as_completed(futures):
                done += 1
                task = futures[future]
                try:
                    r = future.result()
                    results.append(r)
                    status = "OK" if r['success'] else "FAIL"
                    self.logger.info(
                        f"[{done}/{len(tasks)}] Task {r['task_id']} {status} "
                        f"({r.get('duration', 0):.1f}s, {len(r.get('modified_files', []))} files)"
                    )
                except Exception as e:
                    self.logger.error(f"Task {task['task_id']} exception: {e}")
                    results.append({'task_id': task['task_id'], 'success': False, 'error': str(e)})

        # 合并已完成的结果 + 本次结果
        all_results = self._load_completed_results()
        self._save_summary(all_results)
        return all_results

    def _save_summary(self, results: List[Dict[str, Any]]):
        summary = {
            'agent': 'claude-code',
            'total': len(results),
            'successful': sum(1 for r in results if r.get('success')),
            'failed': sum(1 for r in results if not r.get('success')),
            'total_duration': sum(r.get('duration', 0) for r in results),
            'avg_duration': (sum(r.get('duration', 0) for r in results) / len(results)) if results else 0,
            'timestamp': datetime.now().isoformat(),
            'results': results,
        }
        path = os.path.join(self.output_dir, 'summary.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Claude Code Batch Summary")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Total: {summary['total']}")
        self.logger.info(f"Successful: {summary['successful']}")
        self.logger.info(f"Failed: {summary['failed']}")
        self.logger.info(f"Total Duration: {summary['total_duration']:.1f}s")
        self.logger.info(f"Avg Duration: {summary['avg_duration']:.1f}s")
        self.logger.info(f"Summary: {path}")


def parse_args():
    parser = argparse.ArgumentParser(description='Batch Claude Code Runner')
    parser.add_argument('--input', '-i', required=True, help='worktree_records.csv')
    parser.add_argument('--output', '-o', required=True, help='输出目录')
    parser.add_argument('--claude-path', help='claude可执行文件路径')
    parser.add_argument('--model', '-m', help='模型名称 (如 claude-sonnet-4-20250514)')
    parser.add_argument('--workers', '-w', type=int, default=2)
    parser.add_argument('--timeout', '-t', type=int, default=1800)
    parser.add_argument('--status', nargs='+', help='状态过滤')
    parser.add_argument('--projects', '-p', nargs='+')
    parser.add_argument('--types', nargs='+')
    parser.add_argument('--limit', '-l', type=int)
    parser.add_argument('--no-resume', action='store_true',
                        help='禁用断点续传（默认会跳过已成功的任务）')
    parser.add_argument('--retry-failed', action='store_true',
                        help='重试之前失败的任务')
    parser.add_argument('--verbose', '-v', action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logger(level='DEBUG' if args.verbose else 'INFO')
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Batch Claude Code Runner")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        runner = ClaudeCodeRunner(
            input_csv=args.input,
            output_dir=args.output,
            claude_path=args.claude_path,
            workers=args.workers,
            timeout=args.timeout,
            model=args.model,
        )
        results = runner.run_batch(
            status_filter=args.status,
            project_filter=args.projects,
            type_filter=args.types,
            limit=args.limit,
            resume=not args.no_resume,
            retry_failed=args.retry_failed,
        )
        success = sum(1 for r in results if r.get('success'))
        logger.info(f"\nDone: {success} successful, {len(results) - success} failed")
        return 0
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
