#!/usr/bin/env python3
"""
Batch Codex Runner - batchexecuteOpenAI Codex CLI进行obsolete testsidentify和update

Codex CLI 命令:
  codex exec -C <dir> --full-auto "<prompt>"

使用Example:
---------
# batchexecute
python baseline/codex/scripts/batch_codex_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/results \
  --workers 2 --status ready

# 指定model
python baseline/codex/scripts/batch_codex_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/results \
  --model o3

# 限制数量测试
python baseline/codex/scripts/batch_codex_runner.py \
  -i /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/worktree_records.csv \
  -o /Users/mac/Desktop/TestUpdate/TUDataset/agents/codex/results \
  --limit 5 --projects commons-csv
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
CODEX_DIR = os.path.dirname(SCRIPT_DIR)
BASELINE_DIR = os.path.dirname(CODEX_DIR)
PROJECT_ROOT = os.path.dirname(BASELINE_DIR)
sys.path.insert(0, PROJECT_ROOT)

from utils.logger import setup_logger, get_logger
from baseline.shared_test_update_prompt import format_task_prompt


def detect_modified_files(worktree_path: str) -> List[str]:
    """detectworktree中修改的file"""
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


def run_codex_task(task_id: int,
                   worktree_path: str,
                   prompt: str,
                   codex_path: str,
                   output_dir: str,
                   timeout: int,
                   model: str = None,
                   maven_repo_local: str = None) -> Dict[str, Any]:
    """
    in独立process中execute单个Codextask

    Codex CLI 使用: codex exec -C <dir> --full-auto "<prompt>"
    """
    result = {
        'task_id': task_id,
        'worktree_path': worktree_path,
        'agent': 'codex',
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

    # saveprompt
    with open(prompt_file, 'w', encoding='utf-8') as f:
        f.write(prompt)

    try:
        start_time = time.time()

        # 构建Codex命令
        # codex exec -C <dir> --full-auto "<prompt>"
        cmd = [codex_path, 'exec', '-C', worktree_path, '--dangerously-bypass-approvals-and-sandbox', prompt]
        if model:
            cmd.extend(['-m', model])

        env = os.environ.copy()
        if maven_repo_local:
            repo_local = maven_repo_local
            if not os.path.isabs(repo_local):
                repo_local = os.path.join(worktree_path, repo_local)
            os.makedirs(repo_local, exist_ok=True)
            extra_opt = f"-Dmaven.repo.local={repo_local}"
            env["MAVEN_OPTS"] = f"{env.get('MAVEN_OPTS', '').strip()} {extra_opt}".strip()
            env["MAVEN_ARGS"] = f"{env.get('MAVEN_ARGS', '').strip()} {extra_opt}".strip()

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        end_time = time.time()
        result['exit_code'] = process.returncode
        result['stdout'] = process.stdout
        result['stderr'] = process.stderr
        result['end_time'] = datetime.now().isoformat()
        result['duration'] = end_time - start_time

        # 写log
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"=== COMMAND ===\n{' '.join(cmd[:5])} <prompt>\n\n")
            f.write(f"=== WORKTREE ===\n{worktree_path}\n\n")
            f.write(f"=== EXIT CODE ===\n{process.returncode}\n\n")
            f.write(f"=== STDOUT ===\n{process.stdout}\n\n")
            f.write(f"=== STDERR ===\n{process.stderr}\n")

        if process.returncode == 0:
            result['success'] = True
            result['modified_files'] = detect_modified_files(worktree_path)
        else:
            result['error'] = f"codex exited with code {process.returncode}"

    except subprocess.TimeoutExpired:
        result['error'] = f"Timeout after {timeout}s"
        result['end_time'] = datetime.now().isoformat()
    except Exception as e:
        result['error'] = str(e)
        result['end_time'] = datetime.now().isoformat()

    # save results
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


class CodexRunner:
    """Codex CLI batchexecute器"""

    def __init__(self, input_csv: str, output_dir: str,
                 codex_path: str = None, workers: int = 2,
                 timeout: int = 1800, model: str = None,
                 maven_repo_local: str = None):
        self.input_csv = input_csv
        self.output_dir = output_dir
        self.codex_path = codex_path or self._find_codex()
        self.workers = workers
        self.timeout = timeout
        self.model = model
        self.maven_repo_local = maven_repo_local
        self.logger = get_logger()

        os.makedirs(output_dir, exist_ok=True)
        for sub in ['logs', 'prompts', 'results']:
            os.makedirs(os.path.join(output_dir, sub), exist_ok=True)

    def _find_codex(self) -> str:
        for path in ['/opt/homebrew/bin/codex', 'codex']:
            try:
                subprocess.run(['which', path], capture_output=True, check=True)
                return path
            except Exception:
                if os.path.exists(path):
                    return path
        raise RuntimeError("codex not found. Install with: npm install -g @openai/codex")

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
        if self.maven_repo_local:
            additional_context += (
                f"\n\n## Maven Environment\n"
                f"A prewarmed local Maven repository is available at:\n"
                f"`{self.maven_repo_local}`\n"
                f"When running Maven, always include:\n"
                f"`-Dmaven.repo.local={self.maven_repo_local}`\n"
                f"to avoid downloading dependencies repeatedly."
            )
        return format_task_prompt(commit_type, project_name, additional_context)

    def _is_task_completed(self, task_id: int) -> bool:
        """checktask是否已successcomplete（用于断点续传）"""
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
        """load所有已complete的result（用于汇总）"""
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
        batchexecutetask

        Args:
            resume: skip已successcomplete的task（断点续传，default开启）
            retry_failed: 重试之前fail的task
        """
        df = self.load_records(status_filter, project_filter, type_filter)
        if limit:
            df = df.head(limit)

        if len(df) == 0:
            self.logger.warning("No records to process")
            return []

        # 构建task列表，支持断点续传
        tasks = []
        skipped = 0
        for _, row in df.iterrows():
            record = row.to_dict()
            task_id = record.get('task_id', 0)

            if resume and self._is_task_completed(task_id):
                skipped += 1
                continue

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
            self.logger.info(f"skip {skipped} 个已complete的task（断点续传）")

        if len(tasks) == 0:
            self.logger.info("所有task已complete，无需execute")
            all_results = self._load_completed_results()
            self._save_summary(all_results)
            return all_results

        self.logger.info(f"待execute: {len(tasks)} 个task, workers={self.workers}")

        results = []
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(
                    run_codex_task,
                    t['task_id'], t['worktree_path'], t['prompt'],
                    self.codex_path, self.output_dir, self.timeout,
                    self.model,
                    self.maven_repo_local,
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

        all_results = self._load_completed_results()
        self._save_summary(all_results)
        return all_results

    def _save_summary(self, results: List[Dict[str, Any]]):
        summary = {
            'agent': 'codex',
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
        self.logger.info(f"Codex Batch Summary")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"Total: {summary['total']}")
        self.logger.info(f"Successful: {summary['successful']}")
        self.logger.info(f"Failed: {summary['failed']}")
        self.logger.info(f"Total Duration: {summary['total_duration']:.1f}s")
        self.logger.info(f"Avg Duration: {summary['avg_duration']:.1f}s")
        self.logger.info(f"Summary: {path}")


def parse_args():
    parser = argparse.ArgumentParser(description='Batch Codex Runner')
    parser.add_argument('--input', '-i', required=True, help='worktree_records.csv')
    parser.add_argument('--output', '-o', required=True, help='output directory')
    parser.add_argument('--codex-path', help='codex可executefile path')
    parser.add_argument('--model', '-m', help='model名称 (如 o3, o4-mini)')
    parser.add_argument('--maven-repo-local', help='为Codextask指定本地Mavenrepository path')
    parser.add_argument('--workers', '-w', type=int, default=2)
    parser.add_argument('--timeout', '-t', type=int, default=1800)
    parser.add_argument('--status', nargs='+', help='状态过滤')
    parser.add_argument('--projects', '-p', nargs='+')
    parser.add_argument('--types', nargs='+')
    parser.add_argument('--limit', '-l', type=int)
    parser.add_argument('--no-resume', action='store_true',
                        help='禁用断点续传（default会skip已success的task）')
    parser.add_argument('--retry-failed', action='store_true',
                        help='重试之前fail的task')
    parser.add_argument('--verbose', '-v', action='store_true')
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logger(level='DEBUG' if args.verbose else 'INFO')
    logger = get_logger()

    logger.info("=" * 60)
    logger.info("Batch Codex Runner")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    logger.info("Input Parameters:")
    logger.info(f"  input: {args.input}")
    logger.info(f"  output: {args.output}")
    logger.info(f"  codex_path: {args.codex_path or '(auto)'}")
    logger.info(f"  model: {args.model or '(default)'}")
    logger.info(f"  maven_repo_local: {args.maven_repo_local or '(maven default ~/.m2/repository)'}")
    logger.info(f"  workers: {args.workers}")
    logger.info(f"  timeout: {args.timeout}")
    logger.info(f"  status_filter: {args.status or '(none)'}")
    logger.info(f"  project_filter: {args.projects or '(none)'}")
    logger.info(f"  type_filter: {args.types or '(none)'}")
    logger.info(f"  limit: {args.limit if args.limit is not None else '(none)'}")
    logger.info(f"  resume: {not args.no_resume}")
    logger.info(f"  retry_failed: {args.retry_failed}")
    logger.info(f"  verbose: {args.verbose}")
    logger.info("-" * 60)

    try:
        runner = CodexRunner(
            input_csv=args.input,
            output_dir=args.output,
            codex_path=args.codex_path,
            workers=args.workers,
            timeout=args.timeout,
            model=args.model,
            maven_repo_local=args.maven_repo_local,
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
