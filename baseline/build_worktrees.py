#!/usr/bin/env python3
"""TUDataset/
  ├── agents/
"""

import os
import re
import sys
import shutil
import argparse
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from config import Config
from utils.logger import setup_logger, get_logger

AGENTS = ["opencode", "claude-code", "codex"]

# outputCSV
OUTPUT_COLUMNS = [
    "task_id", "project", "project_path", "worktree_path",
    "v_minus_1_commit", "v_0_5_commit", "v_0_5_branch", "v_0_commit",
    "type", "status", "created_at", "error_message",
    "compile_success", "test_success",
    "line_coverage_overlap", "branch_coverage_overlap",
    "modification_score", "overall_score",
    "evaluated_at", "notes",
]


# ============================================================
# ============================================================

def _git(repo_path: str,
         *args,
         timeout: int = 120,
         text: bool = True) -> subprocess.CompletedProcess:
    
    return subprocess.run(
        ['git'] + list(args),
        cwd=repo_path,
        capture_output=True,
        text=text,
        timeout=timeout
    )


def _get_source_only_diff(repo_path: str, parent_hash: str, gt_commit: str) -> Optional[bytes]:
    
    result = _git(repo_path, 'diff', parent_hash, gt_commit, text=False)
    if result.returncode != 0:
        return None

    full_diff = result.stdout
    if not full_diff:
        return b""

    source_sections = []
    sections = re.split(br'(?=^diff --git )', full_diff, flags=re.MULTILINE)
    for sec in sections:
        if not sec.strip():
            continue
        match = re.search(br'diff --git a/(.*?) b/', sec)
        if not match:
            continue
        path = match.group(1).decode('utf-8', errors='ignore')
        # skiptest files
        if any(p in path for p in Config.TEST_PATH_PATTERNS):
            continue
        source_sections.append(sec)

    return b''.join(source_sections)


def _strip_binary_hunks(patch: bytes) -> bytes:
    
    result = []
    sections = re.split(br'(?=^diff --git )', patch, flags=re.MULTILINE)
    for sec in sections:
        if not sec.strip():
            continue
        if b'GIT binary patch' in sec:
            continue
        if re.search(br'^Binary files .+ differ', sec, re.MULTILINE):
            continue
        if not (re.search(br'^--- ', sec, re.MULTILINE) and
                re.search(br'^\+\+\+ ', sec, re.MULTILINE)):
            continue
        result.append(sec)
    return b''.join(result)


def _ensure_git_identity(worktree_path: str):
    
    name = _git(worktree_path, 'config', '--get', 'user.name')
    if name.returncode != 0 or not name.stdout.strip():
        _git(worktree_path, 'config', 'user.name', 'tubench-bot')
    email = _git(worktree_path, 'config', '--get', 'user.email')
    if email.returncode != 0 or not email.stdout.strip():
        _git(worktree_path, 'config', 'user.email', 'tubench-bot@local')


def _get_commit_message(repo_path: str, commit: str) -> Optional[str]:
    
    r = _git(repo_path, 'log', '-1', '--pretty=%B', commit)
    if r.returncode != 0:
        return None
    msg = r.stdout.strip()
    return msg or None


def create_v05_worktree(repo_path: str,
                        gt_commit: str,
                        worktree_path: str,
                        task_id: int,
                        build_mode: str = "detach") -> Dict[str, Any]:
    
    result = {
        'success': False,
        'worktree_path': worktree_path,
        'v05_commit': None,
        'v05_branch': None,
        'parent_commit': None,
        'gt_commit': gt_commit,
        'task_id': task_id,
        'error': None,
    }

    try:
        # 1. get parent hash
        r = _git(repo_path, 'rev-parse', f'{gt_commit}^')
        if r.returncode != 0:
            result['error'] = f"get {gt_commit[:8]}  parent: {r.stderr.strip()}"
            return result
        parent_hash = r.stdout.strip()
        result['parent_commit'] = parent_hash

        # 2. get source-only diff
        source_diff = _get_source_only_diff(repo_path, parent_hash, gt_commit)
        if source_diff is None:
            result['error'] = f"get {gt_commit[:8]}  diff"
            return result

        # 3. clean up
        _git(repo_path, 'worktree', 'prune')
        if os.path.exists(worktree_path):
            _git(repo_path, 'worktree', 'remove', '--force', worktree_path)
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)
        _git(repo_path, 'worktree', 'prune')

        branch_name = None
        if build_mode == "branch":
            # branch
            base = os.path.basename(worktree_path).replace('_eval', '')
            branch_name = f"eval/{base}"
            _git(repo_path, 'branch', '-D', branch_name)
            r = _git(repo_path, 'worktree', 'add', '-b', branch_name, worktree_path, parent_hash)
        else:
            # detach
            r = _git(repo_path, 'worktree', 'add', '--detach', worktree_path, parent_hash)
        if r.returncode != 0:
            result['error'] = f"create worktree Failed: {r.stderr.strip()}"
            return result
        result['v05_branch'] = branch_name

        # 5. in worktree
        if source_diff and source_diff.strip():
            patch_file = os.path.join(worktree_path, '.tubench_patch.diff')
            try:
                if not source_diff.endswith(b'\n'):
                    source_diff += b'\n'
                with open(patch_file, 'wb') as f:
                    f.write(source_diff)

                r = _git(worktree_path, 'apply', '--whitespace=nowarn', patch_file)
                if r.returncode != 0:
                    r = _git(worktree_path, 'apply', '--3way', '--whitespace=nowarn', patch_file)

                if r.returncode != 0:
                    text_patch = _strip_binary_hunks(source_diff)
                    if text_patch and text_patch.strip():
                        with open(patch_file, 'wb') as f:
                            if not text_patch.endswith(b'\n'):
                                text_patch += b'\n'
                            f.write(text_patch)
                        r = _git(worktree_path, 'apply', '--whitespace=nowarn', patch_file)

                if r.returncode != 0:
                    result['error'] = f"apply patch Failed: {r.stderr.strip()[:200]}"
                    # clean upfail
                    _git(repo_path, 'worktree', 'remove', '--force', worktree_path)
                    if os.path.exists(worktree_path):
                        shutil.rmtree(worktree_path, ignore_errors=True)
                    return result

            finally:
                if os.path.exists(patch_file):
                    os.remove(patch_file)

            # 6. in worktree
            _ensure_git_identity(worktree_path)
            _git(worktree_path, 'add', '-A')
            base_message = _get_commit_message(repo_path, gt_commit) or gt_commit
            commit_message = f"{base_message}\n\n[Source Code Changes Only]"
            commit_ret = _git(worktree_path, 'commit', '-m', commit_message)
            if commit_ret.returncode != 0:
                result['error'] = f"create V-0.5 commit Failed: {commit_ret.stderr.strip()[:200]}"
                _git(repo_path, 'worktree', 'remove', '--force', worktree_path)
                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)
                return result

        # get V-0.5 commit hash
        r = _git(worktree_path, 'rev-parse', 'HEAD')
        result['v05_commit'] = r.stdout.strip()
        if source_diff and source_diff.strip() and result['v05_commit'] == parent_hash:
            result['error'] = "V-0.5 commit （ parent），fail"
            _git(repo_path, 'worktree', 'remove', '--force', worktree_path)
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)
            return result
        result['success'] = True

    except Exception as e:
        result['error'] = str(e)
        # clean up
        if os.path.exists(worktree_path):
            _git(repo_path, 'worktree', 'remove', '--force', worktree_path)
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)

    return result


# ============================================================
# ============================================================

def clone_repos_for_agent(source_repos_dir: str,
                           agent_repos_dir: str,
                           projects: List[str],
                           logger) -> Dict[str, str]:
    
    os.makedirs(agent_repos_dir, exist_ok=True)
    repo_paths = {}

    for project in projects:
        source_path = os.path.join(source_repos_dir, project)
        target_path = os.path.join(agent_repos_dir, project)

        if not os.path.exists(source_path):
            logger.warning(f"in: {source_path}，skip {project}")
            continue

        if os.path.exists(target_path) and os.path.exists(os.path.join(target_path, '.git')):
            logger.info(f"[{project}] inclone，skip")
            repo_paths[project] = target_path
            continue

        logger.info(f"[{project}] : {source_path} -> {target_path}")
        try:
            subprocess.run(
                ['git', 'clone', '--local', source_path, target_path],
                capture_output=True, text=True, check=True, timeout=300
            )
            subprocess.run(
                ['git', 'fetch', '--all'],
                cwd=target_path,
                capture_output=True, text=True, timeout=120
            )
            repo_paths[project] = target_path
            logger.info(f"[{project}] complete")
        except Exception as e:
            logger.error(f"[{project}] Failed: {e}")

    return repo_paths


def load_records(csv_path: str) -> pd.DataFrame:
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path)
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def save_records(df: pd.DataFrame, csv_path: str):
    df.to_csv(csv_path, index=False)


# ============================================================
# ============================================================

def build_worktrees_for_agent(
    agent: str,
    base_dir: str,
    source_repos_dir: str,
    commits_df: pd.DataFrame,
    projects_filter: List[str] = None,
    types_filter: List[str] = None,
    limit: int = None,
    skip_existing: bool = True,
    build_mode: str = "detach",
):
    logger = get_logger()
    logger.info(f"\n{'='*60}")
    logger.info(f" {agent} worktreeenvironment")
    logger.info(f"{'='*60}")

    agent_dir = os.path.join(base_dir, agent)
    repos_dir = os.path.join(agent_dir, "repos")
    worktrees_dir = os.path.join(agent_dir, "worktrees")
    records_csv = os.path.join(agent_dir, "worktree_records.csv")

    os.makedirs(agent_dir, exist_ok=True)
    os.makedirs(worktrees_dir, exist_ok=True)

    df = commits_df.copy()
    if projects_filter:
        df = df[df['Project'].isin(projects_filter)]
    if types_filter:
        df = df[df['Type'].isin(types_filter)]
    if limit:
        df = df.head(limit)

    logger.info(f"process: {len(df)} commit")

    # get
    needed_projects = df['Project'].unique().tolist()

    # 1.
    logger.info(f"1: project {repos_dir}")
    repo_paths = clone_repos_for_agent(source_repos_dir, repos_dir, needed_projects, logger)

    if not repo_paths:
        logger.error("project，")
        return

    # 2. load
    records_df = load_records(records_csv)
    existing_commits = set()
    if skip_existing and len(records_df) > 0:
        existing_commits = set(records_df['v_0_commit'].dropna().astype(str))

    # 3.
    logger.info(f"2: worktree {worktrees_dir}")
    new_records = []
    processed = 0
    skipped = 0
    task_counter = len(records_df)

    for idx, row in df.iterrows():
        project = row['Project']
        commit_id = str(row['FullHash']) if 'FullHash' in row else str(row['CommitID'])
        commit_type = row['Type']

        # skip
        if commit_id[:8] in existing_commits:
            skipped += 1
            continue

        # checkproject
        project_path = repo_paths.get(project)
        if not project_path:
            logger.warning(f"[{project}] ，skip {commit_id[:8]}")
            continue

        processed += 1
        task_counter += 1
        task_id = task_counter

        # generate worktree path
        worktree_path = os.path.join(
            worktrees_dir,
            f"{project}-task_{task_id:03d}_eval"
        )

        logger.info(f"[{processed}/{len(df) - skipped}] {agent}/{project}/{commit_id[:8]} ({commit_type})")

        record = {
            "task_id": task_id,
            "project": project,
            "project_path": project_path,
            "v_0_commit": commit_id[:8],
            "type": commit_type,
            "status": "failed",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_message": None,
        }

        wt_result = create_v05_worktree(
            repo_path=project_path,
            gt_commit=commit_id,
            worktree_path=worktree_path,
            task_id=task_id,
            build_mode=build_mode,
        )

        if wt_result['success']:
            record["status"] = "ready"
            record["worktree_path"] = wt_result['worktree_path']
            record["v_minus_1_commit"] = wt_result['parent_commit'][:8] if wt_result['parent_commit'] else None
            record["v_0_5_commit"] = wt_result['v05_commit'][:8] if wt_result['v05_commit'] else None
            record["v_0_5_branch"] = wt_result.get('v05_branch')
        else:
            record["error_message"] = wt_result.get('error', 'Unknown error')
            logger.warning(f"  Failed: {record['error_message']}")

        new_records.append(record)

        if processed % 20 == 0:
            temp_df = pd.concat([records_df, pd.DataFrame(new_records)], ignore_index=True)
            save_records(temp_df, records_csv)
            logger.info(f"  save ({processed} )")

    if new_records:
        records_df = pd.concat([records_df, pd.DataFrame(new_records)], ignore_index=True)
    save_records(records_df, records_csv)

    # prune clean up stale worktree
    for project_path in repo_paths.values():
        _git(project_path, 'worktree', 'prune')

    success = len([r for r in new_records if r['status'] == 'ready'])
    fail = len([r for r in new_records if r['status'] == 'failed'])
    logger.info(f"\n[{agent}] complete:  {success} ��, {fail} fail, skip {skipped}")
    logger.info(f"[{agent}] recordfile: {records_csv}")
    logger.info(f"[{agent}] record: {len(records_df)}")


# ============================================================
# clean up & statistics
# ============================================================

def cmd_build(args):
    logger = get_logger()
    if args.input.endswith('.xlsx') or args.input.endswith('.xls'):
        commits_df = pd.read_excel(args.input)
    else:
        try:
            commits_df = pd.read_csv(args.input)
        except Exception:
            commits_df = pd.read_excel(args.input)
    logger.info(f"load {len(commits_df)} commitrecord")

    agents = args.agents or AGENTS
    for agent in agents:
        if agent not in AGENTS:
            logger.warning(f"agent: {agent}，skip")
            continue
        build_worktrees_for_agent(
            agent=agent,
            base_dir=args.base_dir,
            source_repos_dir=args.source_repos,
            commits_df=commits_df,
            projects_filter=args.projects,
            types_filter=args.types,
            limit=args.limit,
            skip_existing=not args.no_skip,
            build_mode=args.build_mode,
        )


def cmd_clean(args):
    logger = get_logger()
    agents = args.agents or AGENTS

    for agent in agents:
        agent_dir = os.path.join(args.base_dir, agent)
        repos_dir = os.path.join(agent_dir, "repos")
        worktrees_dir = os.path.join(agent_dir, "worktrees")

        if not os.path.exists(agent_dir):
            logger.info(f"[{agent}] directory does not exist，skip")
            continue

        logger.info(f"\nclean up {agent} ...")
        cleaned = 0

        # clean up worktree directory
        if os.path.exists(worktrees_dir):
            for name in os.listdir(worktrees_dir):
                path = os.path.join(worktrees_dir, name)
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                    cleaned += 1

        # prune worktree
        branches_deleted = 0
        if os.path.exists(repos_dir):
            for project in os.listdir(repos_dir):
                project_path = os.path.join(repos_dir, project)
                if not os.path.isdir(project_path):
                    continue
                # prune stale worktree
                _git(project_path, 'worktree', 'prune')
                # delete
                r = _git(project_path, 'branch', '--list', 'eval/*')
                if r.returncode == 0 and r.stdout.strip():
                    for line in r.stdout.strip().splitlines():
                        branch = line.strip().lstrip('* ')
                        if branch:
                            dr = _git(project_path, 'branch', '-D', branch)
                            if dr.returncode == 0:
                                branches_deleted += 1

        records_csv = os.path.join(agent_dir, "worktree_records.csv")
        if os.path.exists(records_csv):
            os.remove(records_csv)

        logger.info(f"[{agent}] clean upcomplete: {cleaned} worktree, {branches_deleted} evalbranch")


def cmd_stats(args):
    agents = args.agents or AGENTS

    for agent in agents:
        agent_dir = os.path.join(args.base_dir, agent)
        records_csv = os.path.join(agent_dir, "worktree_records.csv")

        print(f"\n{'='*60}")
        print(f"Agent: {agent}")
        print(f"{'='*60}")

        if not os.path.exists(records_csv):
            print("  (record)")
            continue

        df = pd.read_csv(records_csv)
        print(f"  record: {len(df)}")
        print(f"  :")
        for status, count in df['status'].value_counts().items():
            print(f"    {status}: {count}")
        print(f"  project:")
        for project, count in df['project'].value_counts().items():
            print(f"    {project}: {count}")
        print(f"  class:")
        for t, count in df['type'].value_counts().items():
            print(f"    {t}: {count}")


def parse_args():
    parser = argparse.ArgumentParser(
        description='Worktree - coding agentisolatedenvironment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--verbose', '-v', action='store_true')

    sub = parser.add_subparsers(dest='command')

    bp = sub.add_parser('build', help='worktree')
    bp.add_argument('--input', '-i', required=True, help='commit CSVfile path')
    bp.add_argument('--base-dir', '-b', required=True, help='agentsdirectory')
    bp.add_argument('--source-repos', '-s', required=True, help='projectdirectory')
    bp.add_argument('--agents', '-a', nargs='+', choices=AGENTS)
    bp.add_argument('--projects', '-p', nargs='+')
    bp.add_argument('--types', '-t', nargs='+')
    bp.add_argument('--limit', '-l', type=int)
    bp.add_argument('--no-skip', action='store_true', help='skipinrecord')
    bp.add_argument('--build-mode', choices=['detach', 'branch'], default='detach',
                    help='worktree : detach() / branch()')

    cp = sub.add_parser('clean', help='clean upworktree')
    cp.add_argument('--base-dir', '-b', required=True)
    cp.add_argument('--agents', '-a', nargs='+', choices=AGENTS)

    sp = sub.add_parser('stats', help='statistics')
    sp.add_argument('--base-dir', '-b', required=True)
    sp.add_argument('--agents', '-a', nargs='+', choices=AGENTS)

    return parser.parse_args()


def main():
    args = parse_args()
    setup_logger(level='DEBUG' if args.verbose else 'INFO')

    if not args.command:
        print(": build / clean / stats。 --help 。")
        return 1

    cmds = {'build': cmd_build, 'clean': cmd_clean, 'stats': cmd_stats}
    return cmds[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
