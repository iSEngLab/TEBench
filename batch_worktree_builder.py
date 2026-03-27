#!/usr/bin/env python3
"""
Batch Worktree Builder
Reads the commit list from commit_summary.xlsx, creates worktrees in batch, and maintains an Excel record table.

Command examples:
---------
# Build worktrees of type1 and type2 for the commons-csv project
python batch_worktree_builder.py --verbose build \
  -i ../commit_summary.xlsx \
  -o /Users/mac/Desktop/TestUpdate/dataset/worktree_records.xlsx \
  --eval-dir /Users/mac/Desktop/TestUpdate/dataset/commons-csv \
  --projects commons-csv \
  --types type1 type2

# View statistics
python batch_worktree_builder.py stats -o /Users/mac/Desktop/TestUpdate/dataset/worktree_records.xlsx

# Update evaluation results
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

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, AnalysisConfig
from utils.logger import setup_logger, get_logger
from evaluation import WorktreeManager


# Project path mapping (project name -> local repository path)
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

# Column definitions for the output Excel file
OUTPUT_COLUMNS = [
    "task_id",           # Task ID
    "project",           # Project name
    "project_path",      # Original project path
    "worktree_path",     # Worktree path
    "v_minus_1_commit",  # V-1 commit (parent)
    "v_0_5_commit",      # V-0.5 commit (generated)
    "v_0_commit",        # V0 commit (GT)
    "type",              # Commit type (type1/type2 etc.)
    "status",            # Status: pending/ready/evaluated/failed
    "created_at",        # Creation time
    "error_message",     # Error message
    # Reserved columns for evaluation metrics
    "compile_success",   # Whether compilation succeeded
    "test_success",      # Whether tests succeeded
    "line_coverage_overlap",    # Line coverage overlap ratio
    "branch_coverage_overlap",  # Branch coverage overlap ratio
    "modification_score",       # Modification effort score
    "overall_score",            # Overall score
    "evaluated_at",             # Evaluation time
    "notes",                    # Notes
]


class BatchWorktreeBuilder:
    """Batch Worktree Builder"""

    def __init__(self,
                 input_excel: str,
                 output_excel: str,
                 eval_dir: str = None,
                 project_paths: Dict[str, str] = None):
        """
        Initialize

        Args:
            input_excel: Path to the input commit_summary.xlsx
            output_excel: Path to the output record table
            eval_dir: Worktree output directory
            project_paths: Project path mapping
        """
        self.input_excel = input_excel
        self.output_excel = output_excel
        self.eval_dir = eval_dir or WorktreeManager.DEFAULT_EVAL_DIR
        self.project_paths = project_paths or PROJECT_PATHS

        self.logger = get_logger()

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_excel) or '.', exist_ok=True)
        os.makedirs(self.eval_dir, exist_ok=True)

    def load_input_commits(self) -> pd.DataFrame:
        """Load the input commit list (supports .xlsx and .csv)"""
        if self.input_excel.endswith('.csv'):
            df = pd.read_csv(self.input_excel)
        else:
            df = pd.read_excel(self.input_excel)
        self.logger.info(f"Loaded {len(df)} commit records")
        return df

    def load_or_create_output(self) -> pd.DataFrame:
        """Load or create the output record table (supports .xlsx and .csv)"""
        if os.path.exists(self.output_excel):
            if self.output_excel.endswith('.csv'):
                df = pd.read_csv(self.output_excel)
            else:
                df = pd.read_excel(self.output_excel)
            self.logger.info(f"Loaded existing record table with {len(df)} records")
        else:
            df = pd.DataFrame(columns=OUTPUT_COLUMNS)
            self.logger.info("Creating new record table")
        return df

    def save_output(self, df: pd.DataFrame):
        """Save the output record table (supports .xlsx and .csv, saves both formats simultaneously)"""
        # Save main file
        if self.output_excel.endswith('.csv'):
            df.to_csv(self.output_excel, index=False)
        else:
            df.to_excel(self.output_excel, index=False)
        self.logger.info(f"Saved record table to {self.output_excel}")

        # Also save the other format
        if self.output_excel.endswith('.xlsx'):
            csv_path = self.output_excel.replace('.xlsx', '.csv')
            df.to_csv(csv_path, index=False)
            self.logger.debug(f"Also saved CSV to {csv_path}")
        elif self.output_excel.endswith('.csv'):
            xlsx_path = self.output_excel.replace('.csv', '.xlsx')
            df.to_excel(xlsx_path, index=False)
            self.logger.debug(f"Also saved Excel to {xlsx_path}")

    def get_project_path(self, project_name: str) -> Optional[str]:
        """Get project path"""
        path = self.project_paths.get(project_name)
        if path and os.path.exists(path):
            return path
        return None

    def build_single_worktree(self,
                               project: str,
                               commit_id: str,
                               commit_type: str) -> Dict[str, Any]:
        """
        Build a single worktree

        Args:
            project: Project name
            commit_id: Commit hash
            commit_type: Commit type

        Returns:
            dict: Build result
        """
        result = {
            "project": project,
            "v_0_commit": commit_id[:8],
            "type": commit_type,
            "status": "failed",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_message": None,
        }

        # Get project path
        project_path = self.get_project_path(project)
        if not project_path:
            result["error_message"] = f"Project path not configured or does not exist: {project}"
            return result

        result["project_path"] = project_path

        try:
            # Create WorktreeManager
            manager = WorktreeManager(project_path, self.eval_dir)

            # Get cache directory
            cache_dir = os.path.join(AnalysisConfig.CACHE_DIR, project)

            # Prepare worktree
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
            self.logger.error(f"Failed to build worktree [{project}/{commit_id[:8]}]: {e}")

        return result

    def build_batch(self,
                    projects: List[str] = None,
                    types: List[str] = None,
                    limit: int = None,
                    skip_existing: bool = True) -> pd.DataFrame:
        """
        Build worktrees in batch

        Args:
            projects: List of projects to process (None means all)
            types: List of types to process (None means all)
            limit: Maximum number to process
            skip_existing: Whether to skip already existing records

        Returns:
            DataFrame: Updated record table
        """
        # Load data
        input_df = self.load_input_commits()
        output_df = self.load_or_create_output()

        # Filter
        filtered_df = input_df.copy()
        if projects:
            filtered_df = filtered_df[filtered_df['Project'].isin(projects)]
        if types:
            filtered_df = filtered_df[filtered_df['Type'].isin(types)]

        self.logger.info(f"After filtering, items to process: {len(filtered_df)}")

        # Get already-processed commits
        existing_commits = set()
        if skip_existing and len(output_df) > 0:
            existing_commits = set(output_df['v_0_commit'].dropna().astype(str))

        # Process
        processed = 0
        new_records = []

        for idx, row in filtered_df.iterrows():
            project = row['Project']
            commit_id = str(row['CommitID'])
            commit_type = row['Type']

            # Skip already existing (compare first 8 characters)
            if commit_id[:8] in existing_commits:
                self.logger.debug(f"Skipping existing: {project}/{commit_id[:8]}")
                continue

            # Check limit
            if limit and processed >= limit:
                self.logger.info(f"Reached processing limit: {limit}")
                break

            # Build worktree
            self.logger.info(f"[{processed+1}] Processing {project}/{commit_id[:8]} ({commit_type})")
            result = self.build_single_worktree(project, commit_id, commit_type)
            new_records.append(result)

            processed += 1

            # Periodic save
            if processed % 10 == 0:
                temp_df = pd.concat([output_df, pd.DataFrame(new_records)], ignore_index=True)
                self.save_output(temp_df)
                self.logger.info(f"Processed {processed} items, intermediate save")

        # Merge results
        if new_records:
            output_df = pd.concat([output_df, pd.DataFrame(new_records)], ignore_index=True)

        # Final save
        self.save_output(output_df)

        # Statistics
        success_count = len([r for r in new_records if r['status'] == 'ready'])
        fail_count = len([r for r in new_records if r['status'] == 'failed'])
        self.logger.info(f"\nProcessing complete: succeeded {success_count}, failed {fail_count}")

        return output_df

    def clean_project_branches(self,
                               projects: List[str] = None,
                               eval_dir: str = None,
                               dry_run: bool = False) -> Dict[str, Any]:
        """
        Clean up eval/* branches and corresponding worktree directories created by this tool for the specified projects.

        Branch naming convention: eval/<project>-task_NNN
        Worktree directory convention: <eval_dir>/<project>-task_NNN_eval

        Args:
            projects: List of projects to clean (None means all configured projects)
            eval_dir: Worktree output directory (None uses the instance default)
            dry_run: Print only, do not actually delete

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
                self.logger.warning(f"[{project}] Path not configured or does not exist, skipping")
                continue

            info = {'branches': [], 'worktrees': [], 'errors': []}
            summary[project] = info
            pattern = re.compile(rf'^eval/{re.escape(project)}-task_(\d+)$')

            try:
                repo = Repo(repo_path)
            except Exception as e:
                info['errors'].append(f"Failed to open repository: {e}")
                continue

            # 1. Find all matching branches
            try:
                all_branches = repo.git.branch().split('\n')
            except Exception as e:
                info['errors'].append(f"Failed to list branches: {e}")
                continue

            matched_branches = []
            for b in all_branches:
                b = b.strip().lstrip('* ')
                if pattern.match(b):
                    matched_branches.append(b)

            if not matched_branches:
                self.logger.info(f"[{project}] No eval/* branches found, nothing to clean")
                continue

            self.logger.info(f"[{project}] Found {len(matched_branches)} branches to clean")

            # 2. Get all current worktree info (path -> branch mapping)
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
                        # git output format: refs/heads/eval/...
                        if current_wt_branch.startswith('refs/heads/'):
                            current_wt_branch = current_wt_branch[len('refs/heads/'):]
                        if current_wt_branch and current_wt_path:
                            worktree_branch_map[current_wt_branch] = current_wt_path
            except Exception as e:
                self.logger.debug(f"[{project}] Failed to get worktree list: {e}")

            # 3. Clean up one by one
            for branch in matched_branches:
                # 3a. Remove associated worktree first (must be before deleting branch)
                wt_path = worktree_branch_map.get(branch)
                if not wt_path:
                    # Infer directory from naming convention
                    m = pattern.match(branch)
                    if m:
                        task_id = int(m.group(1))
                        wt_path = os.path.join(
                            eval_dir,
                            f"{project}-task_{task_id:03d}_eval"
                        )

                if wt_path and os.path.exists(wt_path):
                    if dry_run:
                        self.logger.info(f"  [dry-run] Removing worktree: {wt_path}")
                    else:
                        try:
                            repo.git.worktree('remove', '--force', wt_path)
                            info['worktrees'].append(wt_path)
                            self.logger.info(f"  ✓ Removed worktree: {wt_path}")
                        except Exception as e:
                            # If worktree remove fails, delete the directory directly
                            try:
                                import shutil
                                shutil.rmtree(wt_path, ignore_errors=True)
                                repo.git.worktree('prune')
                                info['worktrees'].append(wt_path)
                                self.logger.info(f"  ✓ Force-removed worktree directory: {wt_path}")
                            except Exception as e2:
                                info['errors'].append(f"Failed to remove worktree {wt_path}: {e2}")
                                self.logger.warning(f"  ✗ Failed to remove worktree: {e2}")

                # 3b. Delete branch
                if dry_run:
                    self.logger.info(f"  [dry-run] Deleting branch: {branch}")
                else:
                    try:
                        repo.git.branch('-D', branch)
                        info['branches'].append(branch)
                        self.logger.info(f"  ✓ Deleted branch: {branch}")
                    except GitCommandError as e:
                        info['errors'].append(f"Failed to delete branch {branch}: {e}")
                        self.logger.warning(f"  ✗ Failed to delete branch {branch}: {e}")

            # 4. Prune stale references
            if not dry_run:
                try:
                    repo.git.worktree('prune')
                except Exception:
                    pass

            self.logger.info(
                f"[{project}] Done: deleted {len(info['branches'])} branches, "
                f"{len(info['worktrees'])} worktrees, "
                f"{len(info['errors'])} errors"
            )

        return summary

    def update_evaluation_results(self,
                                   task_id: int = None,
                                   worktree_path: str = None,
                                   results: Dict[str, Any] = None):
        """
        Update evaluation results to the record table

        Args:
            task_id: Task ID
            worktree_path: Worktree path
            results: Evaluation result dictionary
        """
        output_df = self.load_or_create_output()

        # Find the record
        mask = None
        if task_id is not None:
            mask = output_df['task_id'] == task_id
        elif worktree_path:
            mask = output_df['worktree_path'] == worktree_path

        if mask is None or not mask.any():
            self.logger.warning("No matching record found")
            return

        # Update evaluation results
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
        """Get statistics"""
        output_df = self.load_or_create_output()

        stats = {
            "total": len(output_df),
            "by_status": output_df['status'].value_counts().to_dict(),
            "by_project": output_df['project'].value_counts().to_dict(),
            "by_type": output_df['type'].value_counts().to_dict(),
        }

        # Evaluation statistics
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
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='Batch Worktree Build Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Build worktrees for all commits
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx

  # Process only specific projects
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --projects commons-csv commons-cli

  # Process only specific types
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --types type1

  # Limit the number of items to process
  python batch_worktree_builder.py build --input ../commit_summary.xlsx --output ./output/worktree_records.xlsx --limit 10

  # View statistics
  python batch_worktree_builder.py stats --output ./output/worktree_records.xlsx
        '''
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # build command
    build_parser = subparsers.add_parser('build', help='Build worktrees in batch')
    build_parser.add_argument('--input', '-i', type=str, required=True,
                              help='Path to the input commit_summary.xlsx')
    build_parser.add_argument('--output', '-o', type=str, required=True,
                              help='Path to the output record table')
    build_parser.add_argument('--eval-dir', type=str,
                              help='Worktree output directory')
    build_parser.add_argument('--projects', '-p', nargs='+',
                              help='List of projects to process')
    build_parser.add_argument('--types', '-t', nargs='+',
                              help='List of types to process')
    build_parser.add_argument('--limit', '-l', type=int,
                              help='Maximum number of items to process')
    build_parser.add_argument('--no-skip', action='store_true',
                              help='Do not skip already existing records')

    # stats command
    stats_parser = subparsers.add_parser('stats', help='View statistics')
    stats_parser.add_argument('--output', '-o', type=str, required=True,
                              help='Path to the record table')

    # clean command
    clean_parser = subparsers.add_parser('clean', help='Clean eval/* branches and worktree directories for specified projects')
    clean_parser.add_argument('--eval-dir', type=str,
                              help='Worktree output directory (must match the one used during build)')
    clean_parser.add_argument('--projects', '-p', nargs='+',
                              help='List of projects to clean (leave empty to clean all configured projects)')
    clean_parser.add_argument('--dry-run', action='store_true',
                              help='Print what would be deleted without actually deleting')

    # update command
    update_parser = subparsers.add_parser('update', help='Update evaluation results')
    update_parser.add_argument('--output', '-o', type=str, required=True,
                               help='Path to the record table')
    update_parser.add_argument('--task-id', type=int,
                               help='Task ID')
    update_parser.add_argument('--worktree', type=str,
                               help='Worktree path')
    update_parser.add_argument('--results', type=str,
                               help='Evaluation result JSON file')

    # Common arguments
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose log output')

    return parser.parse_args()


def cmd_build(args, logger):
    """Execute batch build"""
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
    """Display statistics"""
    builder = BatchWorktreeBuilder(
        input_excel="",  # Not needed
        output_excel=args.output
    )

    stats = builder.get_statistics()

    print("\n" + "=" * 60)
    print("Worktree Build Statistics")
    print("=" * 60)

    print(f"\nTotal records: {stats['total']}")

    print("\nBy status:")
    for status, count in stats.get('by_status', {}).items():
        print(f"  {status}: {count}")

    print("\nBy project:")
    for project, count in stats.get('by_project', {}).items():
        print(f"  {project}: {count}")

    print("\nBy type:")
    for type_, count in stats.get('by_type', {}).items():
        print(f"  {type_}: {count}")

    if 'evaluation' in stats:
        eval_stats = stats['evaluation']
        print(f"\nEvaluation statistics ({eval_stats['count']} records):")
        print(f"  Average line coverage overlap: {eval_stats['avg_line_coverage']:.2%}")
        print(f"  Average branch coverage overlap: {eval_stats['avg_branch_coverage']:.2%}")
        print(f"  Average modification score: {eval_stats['avg_modification_score']:.2%}")
        print(f"  Average overall score: {eval_stats['avg_overall_score']:.2%}")

    return 0


def cmd_clean(args, logger):
    """Clean eval/* branches and worktree directories"""
    builder = BatchWorktreeBuilder(
        input_excel="",
        output_excel="",
        eval_dir=getattr(args, 'eval_dir', None)
    )

    if getattr(args, 'dry_run', False):
        print("[dry-run mode] The following will be deleted (no actual deletion will occur):")

    summary = builder.clean_project_branches(
        projects=args.projects,
        eval_dir=getattr(args, 'eval_dir', None),
        dry_run=getattr(args, 'dry_run', False)
    )

    print("\n" + "=" * 60)
    print("Cleanup Statistics")
    print("=" * 60)
    total_branches = sum(len(v['branches']) for v in summary.values())
    total_wt = sum(len(v['worktrees']) for v in summary.values())
    total_err = sum(len(v['errors']) for v in summary.values())
    for project, info in summary.items():
        print(f"\n{project}:")
        print(f"  Branches deleted: {len(info['branches'])}")
        print(f"  Worktrees deleted: {len(info['worktrees'])}")
        if info['errors']:
            for e in info['errors']:
                print(f"  ✗ {e}")
    print(f"\nTotal: {total_branches} branches, {total_wt} worktrees, {total_err} errors")
    return 0


def cmd_update(args, logger):
    """Update evaluation results"""
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

    print("Evaluation results updated")
    return 0


def main():
    """Main function"""
    args = parse_args()

    # Set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    if not args.command:
        print("Please specify a command. Use --help for usage information.")
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
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
