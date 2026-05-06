#!/usr/bin/env python3
"""Module."""

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

# baseline/opencode/scripts/batch_opencode_runner.py -> TUBench/
script_dir = os.path.dirname(os.path.abspath(__file__))  # scripts/
opencode_dir = os.path.dirname(script_dir)  # opencode/
baseline_dir = os.path.dirname(opencode_dir)  # baseline/
project_root = os.path.dirname(baseline_dir)  # TUBench/
sys.path.insert(0, project_root)

from utils.logger import setup_logger, get_logger
from baseline.shared_test_update_prompt import format_task_prompt

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Warning: pandas not installed. Install with: pip install pandas openpyxl")


class OpenCodeRunner:
    

    def __init__(self,
                 input_excel: str,
                 output_dir: str,
                 opencode_path: str = None,
                 workers: int = 2,
                 timeout: int = 1800,
                 model: str = None):
        """Initialize."""
        if not HAS_PANDAS:
            raise RuntimeError("pandas is required. Install with: pip install pandas openpyxl")

        self.logger = get_logger()

        self.input_excel = input_excel
        self.output_dir = output_dir
        self.opencode_path = opencode_path or self._find_opencode()
        self.workers = workers
        self.timeout = timeout
        self.model = model

        # create output directories
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'logs'), exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'prompts'), exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'results'), exist_ok=True)

    def _find_opencode(self) -> str:
        
        candidates = [
            '/Users/mac/.opencode/bin/opencode',
            os.path.expanduser('~/.opencode/bin/opencode'),
            'opencode',  # on PATH
        ]

        for path in candidates:
            if os.path.exists(path) or self._check_command_exists(path):
                self.logger.info(f"Found opencode at: {path}")
                return path

        raise RuntimeError("opencode not found. Please install or specify path with --opencode-path")

    def _check_command_exists(self, cmd: str) -> bool:
        
        try:
            subprocess.run(['which', cmd], capture_output=True, check=True)
            return True
        except:
            return False

    def load_worktree_records(self,
                              status_filter: List[str] = None,
                              project_filter: List[str] = None,
                              type_filter: List[str] = None) -> pd.DataFrame:
        """loadworktree record
        Args:
"""
        if self.input_excel.endswith('.csv'):
            df = pd.read_csv(self.input_excel)
        else:
            df = pd.read_excel(self.input_excel)
        self.logger.info(f"Loaded {len(df)} worktree records")

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
        """Args:
            record: worktree record
"""
        commit_type = record.get('type', 'unknown')
        project_name = record.get('project', 'unknown')

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
        
        prompt_file = os.path.join(self.output_dir, 'prompts', f'task_{task_id:03d}_prompt.txt')
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        return prompt_file

    def run_opencode_task(self,
                          task_id: int,
                          worktree_path: str,
                          prompt: str) -> Dict[str, Any]:
        """Args:
            task_id: taskID
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

            # saveprompt
            prompt_file = self.save_prompt(task_id, prompt)
            self.logger.debug(f"[Task {task_id}] Saved prompt to {prompt_file}")

            # OpenCode
            cmd = [
                self.opencode_path,
                'run',
                prompt,
                '--dir', worktree_path,
                '--format', 'json',
            ]
            if self.model:
                cmd.extend(['-m', self.model])

            self.logger.debug(f"[Task {task_id}] Running OpenCode in {worktree_path}")
            self.logger.debug(f"[Task {task_id}] Command: {' '.join(cmd)}")

            # executeOpenCode
            with open(log_file, 'w') as log_f:
                process = subprocess.run(
                    cmd,
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout
                )

                # recordoutput
                log_f.write(f"=== STDOUT ===\n{process.stdout}\n")
                log_f.write(f"=== STDERR ===\n{process.stderr}\n")

                result['exit_code'] = process.returncode
                result['stdout'] = process.stdout
                result['stderr'] = process.stderr

            end_time = time.time()
            result['end_time'] = datetime.now().isoformat()
            result['duration'] = end_time - start_time

            # check
            if process.returncode == 0:
                result['success'] = True
                self.logger.debug(f"[Task {task_id}] Completed successfully in {result['duration']:.1f}s")

                # detect
                modified_files = self._detect_modified_files(worktree_path)
                result['modified_files'] = modified_files
                self.logger.debug(f"[Task {task_id}] Modified {len(modified_files)} files")
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

        # save results
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return result

    def _detect_modified_files(self, worktree_path: str) -> List[str]:
        """Args:
            worktree_path: worktree path
"""
        try:
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
                    # format: " M file.java"
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        modified_files.append(parts[1])

            return modified_files

        except Exception as e:
            self.logger.warning(f"Failed to detect modified files: {e}")
            return []

    def _is_task_completed(self, task_id: int) -> bool:
        
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

    def run_batch(self,
                  status_filter: List[str] = None,
                  project_filter: List[str] = None,
                  type_filter: List[str] = None,
                  limit: int = None,
                  resume: bool = True,
                  retry_failed: bool = False) -> List[Dict[str, Any]]:
        """batchexecuteOpenCode task
        Args:
"""
        # loadrecord
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

        tasks = []
        skipped = 0
        for idx, row in df.iterrows():
            task_id = row.get('task_id', idx + 1)
            worktree_path = row['worktree_path']
            record = row.to_dict()

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
                'worktree_path': worktree_path,
                'prompt': self.generate_prompt(record),
            })

        if skipped > 0:
            self.logger.info(f"skip {skipped} completetask（）")

        if len(tasks) == 0:
            self.logger.info("taskcomplete，execute")
            all_results = self._load_completed_results()
            self._generate_summary_report(all_results)
            return all_results

        self.logger.info(f"Processing {len(tasks)} records with {self.workers} workers")

        # parallelexecute
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
                    self.timeout,
                    self.model,
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

                    status = "OK" if result['success'] else "FAIL"
                    self.logger.info(
                        f"[{completed}/{len(tasks)}] Task {result['task_id']} {status} "
                        f"({result.get('duration', 0):.1f}s, {len(result.get('modified_files', []))} files)"
                    )

                except Exception as e:
                    self.logger.error(f"Task {task['task_id']} failed: {e}")
                    results.append({
                        'task_id': task['task_id'],
                        'success': False,
                        'error': str(e)
                    })

        all_results = self._load_completed_results()
        self._generate_summary_report(all_results)

        return all_results

    def _generate_summary_report(self, results: List[Dict[str, Any]]):
        
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
                              timeout: int,
                              model: str = None) -> Dict[str, Any]:
    """Args:
        task_id: taskID
"""
    # inworkerprocess
    runner = OpenCodeRunner(
        input_excel="",
        output_dir=output_dir,
        opencode_path=opencode_path,
        timeout=timeout,
        model=model,
    )

    return runner.run_opencode_task(task_id, worktree_path, prompt)


def parse_args():
    """parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Batch OpenCode Runner - batchexecuteOpenCodeupdate',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--input', '-i', type=str, required=True,
                        help='worktree_records.xlsxpath')
    parser.add_argument('--output', '-o', type=str, required=True,
                        help='output directory')
    parser.add_argument('--opencode-path', type=str,
                        help='opencodeexecutefile path（default）')
    parser.add_argument('--model', '-m', type=str,
                        help='model，format provider/model（ myprovider/claude-sonnet-4-6）')

    parser.add_argument('--workers', '-w', type=int, default=2,
                        help='number of parallel workers（default: 2）')
    parser.add_argument('--timeout', '-t', type=int, default=1800,
                        help='tasktimeout（，default: 1800）')

    parser.add_argument('--status', nargs='+',
                        help='（: ready）')
    parser.add_argument('--projects', '-p', nargs='+',
                        help='project')
    parser.add_argument('--types', nargs='+',
                        help='class（: type1 type2）')
    parser.add_argument('--limit', '-l', type=int,
                        help='process（）')

    parser.add_argument('--no-resume', action='store_true',
                        help='（defaultskipsuccesstask）')
    parser.add_argument('--retry-failed', action='store_true',
                        help='failtask')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='verbose logging output')

    return parser.parse_args()


def main():
    """main function"""
    args = parse_args()

    # set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("="*60)
    logger.info("Batch OpenCode Runner")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # createrunner
        runner = OpenCodeRunner(
            input_excel=args.input,
            output_dir=args.output,
            opencode_path=args.opencode_path,
            workers=args.workers,
            timeout=args.timeout,
            model=args.model,
        )

        # executebatch task
        results = runner.run_batch(
            status_filter=args.status,
            project_filter=args.projects,
            type_filter=args.types,
            limit=args.limit,
            resume=not args.no_resume,
            retry_failed=args.retry_failed,
        )

        # outputresult
        success_count = sum(1 for r in results if r.get('success'))
        fail_count = len(results) - success_count

        logger.info(f"\nCompleted: {success_count} successful, {fail_count} failed")

        return 0 if fail_count == 0 else 1

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
