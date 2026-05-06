"""Module."""

import os
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, Dict, Any

from git import Repo, GitCommandError

from config import Config, AnalysisConfig
from utils.logger import get_logger

logger = get_logger()


def _strip_binary_hunks(patch: str) -> str:
    """
    Remove binary file patch sections from a unified diff, keeping only text-applicable parts.

    Characteristics of binary patch sections:
      - contains a "GIT binary patch" line, or
      - diff header is immediately followed by "Binary files ... differ", or
      - no --- / +++ lines after the index line (cannot be applied as text patch)
    """
    result_sections = []
    # split by "diff --git"
    sections = re.split(r'(?=^diff --git )', patch, flags=re.MULTILINE)
    for sec in sections:
        if not sec.strip():
            continue
        # skip binary sections
        if 'GIT binary patch' in sec:
            continue
        if re.search(r'^Binary files .+ differ', sec, re.MULTILINE):
            continue
        if not (re.search(r'^--- ', sec, re.MULTILINE) and
                re.search(r'^\+\+\+ ', sec, re.MULTILINE)):
            continue
        result_sections.append(sec)
    return ''.join(result_sections)


class WorktreeManager:
    

    # defaultevaluateworktreedirectory
    DEFAULT_EVAL_DIR = "/tmp/tubench_eval"

    def __init__(self, repo_path: str, eval_dir: str = None):

        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        self.repo = Repo(repo_path)
        self.eval_dir = eval_dir or self.DEFAULT_EVAL_DIR

        os.makedirs(self.eval_dir, exist_ok=True)

    def prepare_evaluation_worktree(self,
                                     gt_commit: str,
                                     cache_dir: str = None) -> Dict[str, Any]:
        """1. get V-0.5 information（parent commit + source_only_diff）
        2. createevaluatebranch eval/<gt_commit_short>
"""
        result = {
            'success': False,
            'worktree_path': None,
            'v05_commit': None,
            'v05_branch': None,
            'parent_commit': None,
            'gt_commit': gt_commit,
            'error': None
        }

        try:
            # 1. getV-0.5information（
            v05_info = self._get_v05_info(gt_commit, cache_dir)
            if not v05_info:
                result['error'] = f"getcommit {gt_commit[:8]} V-0.5information"
                return result

            parent_hash = v05_info.get('parent_hash')
            source_only_diff = v05_info.get('source_only_diff')

            if not parent_hash:
                result['error'] = f"commit {gt_commit[:8]} commit"
                return result

            result['parent_commit'] = parent_hash

            # 2. generatetask
            task_id = self._get_next_task_id()
            branch_name = f"eval/{self.project_name}-task_{task_id:03d}"

            # 3. create V-0.5 branch
            v05_commit = self._create_v05_branch(
                parent_hash, source_only_diff, branch_name, gt_commit
            )

            if not v05_commit:
                result['error'] = "createV-0.5branchfail"
                return result

            result['v05_commit'] = v05_commit
            result['v05_branch'] = branch_name
            result['task_id'] = task_id

            # 4. createworktree path
            worktree_path = self._get_worktree_path(task_id)

            # 5.
            if os.path.exists(worktree_path):
                self._cleanup_worktree(worktree_path)

            # 6.
            if not self._create_worktree(v05_commit, worktree_path):
                result['error'] = "createworktreefail"
                return result

            result['success'] = True
            result['worktree_path'] = worktree_path

            logger.info(f"✓ createevaluateworktree: {worktree_path}")
            logger.info(f"✓ V-0.5branch: {branch_name} ({v05_commit[:8]})")
            logger.info(f"✓ parent: {parent_hash[:8]}")

        except Exception as e:
            logger.error(f"evaluateworktreeFailed: {e}")
            result['error'] = str(e)

        return result

    def _create_v05_branch(self,
                           parent_hash: str,
                           source_only_diff: str,
                           branch_name: str,
                           gt_commit: str) -> Optional[str]:
        """Args:
            parent_hash: parent commit hash
"""

        # save
        original_head = self.repo.head.commit.hexsha
        original_branch = None
        try:
            original_branch = self.repo.active_branch.name
        except TypeError:
            pass  # detached HEAD

        try:
            # 1. delete
            try:
                self.repo.git.branch('-D', branch_name)
                logger.debug(f"deleteinbranch: {branch_name}")
            except GitCommandError:
                pass

            # 2.
            self.repo.git.checkout('-b', branch_name, parent_hash)
            logger.debug(f"createbranch {branch_name}  {parent_hash[:8]}")

            # 3.
            if source_only_diff and source_only_diff.strip():
                with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                    if not source_only_diff.endswith('\n'):
                        source_only_diff += '\n'
                    f.write(source_only_diff)
                    patch_file = f.name

                try:
                    process = subprocess.run(
                        ['git', 'apply', '--whitespace=nowarn', patch_file],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if process.returncode != 0:
                        process = subprocess.run(
                            ['git', 'apply', '--3way', '--whitespace=nowarn', patch_file],
                            cwd=self.repo_path,
                            capture_output=True,
                            text=True,
                            timeout=60
                        )

                    if process.returncode != 0:
                        binary_err = (
                            'cannot apply binary patch' in process.stderr
                            or 'lacks the necessary blob' in process.stderr
                        )
                        if binary_err:
                            text_patch = _strip_binary_hunks(source_only_diff)
                            if text_patch and text_patch.strip():
                                with tempfile.NamedTemporaryFile(
                                    mode='w', suffix='.patch', delete=False
                                ) as tf:
                                    if not text_patch.endswith('\n'):
                                        text_patch += '\n'
                                    tf.write(text_patch)
                                    text_patch_file = tf.name
                                try:
                                    process = subprocess.run(
                                        ['git', 'apply', '--whitespace=nowarn',
                                         text_patch_file],
                                        cwd=self.repo_path,
                                        capture_output=True,
                                        text=True,
                                        timeout=60
                                    )
                                    if process.returncode == 0:
                                        logger.warning(
                                            f"skipfile，"
                                        )
                                finally:
                                    if os.path.exists(text_patch_file):
                                        os.remove(text_patch_file)

                    if process.returncode != 0:
                        logger.error(f"patchFailed: {process.stderr}")
                        return None

                finally:
                    if os.path.exists(patch_file):
                        os.remove(patch_file)

                # 4. commit
                self.repo.git.add('-A')

                if self.repo.is_dirty():
                    # get
                    gt_commit_obj = self.repo.commit(gt_commit)
                    original_message = gt_commit_obj.message.strip()

                    commit_message = (
                        f"{original_message}\n\n"
                        f"[Source Code Changes Only]"
                    )
                    self.repo.git.commit('-m', commit_message)

            v05_commit = self.repo.head.commit.hexsha
            logger.debug(f"V-0.5 commit: {v05_commit[:8]}")

            return v05_commit

        except Exception as e:
            logger.error(f"createV-0.5branchFailed: {e}")
            return None

        finally:
            # restore original state
            try:
                if original_branch:
                    self.repo.git.checkout(original_branch)
                else:
                    self.repo.git.checkout(original_head)
            except:
                pass

    def commit_user_changes(self, worktree_path: str,
                            message: str = None) -> Dict[str, Any]:
        """Args:
            worktree_path: worktree path
"""
        result = {
            'success': False,
            'user_commit': None,
            'changed_files': [],
            'error': None
        }

        try:
            worktree_repo = Repo(worktree_path)

            # check
            if not worktree_repo.is_dirty() and not worktree_repo.untracked_files:
                result['error'] = "detect"
                return result

            # get
            changed_files = []
            for item in worktree_repo.index.diff(None):
                changed_files.append(item.a_path)
            changed_files.extend(worktree_repo.untracked_files)
            result['changed_files'] = changed_files

            worktree_repo.git.add('-A')

            # commit
            if not message:
                message = f"[TUBench Evaluation] User test modification"

            worktree_repo.git.commit('-m', message)

            result['success'] = True
            result['user_commit'] = worktree_repo.head.commit.hexsha

            logger.info(f"✓ commit: {result['user_commit'][:8]}")

        except Exception as e:
            logger.error(f"commitFailed: {e}")
            result['error'] = str(e)

        return result

    def get_worktree_info(self, worktree_path: str) -> Optional[Dict[str, Any]]:
        """Args:
            worktree_path: worktree path
"""
        try:
            from git import Repo
            import re

            worktree_repo = Repo(worktree_path)

            # get
            v05_commit = worktree_repo.head.commit.hexsha

            # get parent commit（V-0.5
            parent_commit = None
            if worktree_repo.head.commit.parents:
                parent_commit = worktree_repo.head.commit.parents[0].hexsha

            # pathformat: {project}-task_{id}_eval
            worktree_name = os.path.basename(worktree_path)
            task_id = None
            match = re.search(r'-task_(\d+)_eval$', worktree_name)
            if match:
                task_id = int(match.group(1))

            return {
                'v05_commit': v05_commit,
                'parent_commit': parent_commit,
                'task_id': task_id,
                'worktree_path': worktree_path
            }

        except Exception as e:
            logger.debug(f"getworktreeinformationFailed: {e}")
            return None

    def cleanup_worktree(self, worktree_path: str) -> bool:
        """clean upworktree
        Args:
"""
        return self._cleanup_worktree(worktree_path)

    def cleanup_all_worktrees(self) -> int:

        count = 0
        if os.path.exists(self.eval_dir):
            for name in os.listdir(self.eval_dir):
                path = os.path.join(self.eval_dir, name)
                if os.path.isdir(path) and name.startswith(self.project_name):
                    if self._cleanup_worktree(path):
                        count += 1

        # executegit worktree prune
        try:
            self.repo.git.worktree('prune')
        except:
            pass

        logger.info(f"clean up {count} evaluateworktree")
        return count

    def _get_v05_info(self, gt_commit: str, cache_dir: str = None) -> Optional[Dict]:
        
        if cache_dir:
            cache_file = os.path.join(
                cache_dir,
                f"{self.project_name}_{gt_commit}_execution.json"
            )
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r') as f:
                        cache_data = json.load(f)
                    data = cache_data.get('data', {})
                    return {
                        'parent_hash': data.get('parent_hash'),
                        'source_only_diff': data.get('diff_info', {}).get('source_only_diff')
                    }
                except Exception as e:
                    logger.debug(f"cacheFailed: {e}")

        return self._generate_v05_info(gt_commit)

    def _generate_v05_info(self, gt_commit: str) -> Optional[Dict]:
        
        try:
            commit = self.repo.commit(gt_commit)
            if not commit.parents:
                return None

            parent_hash = commit.parents[0].hexsha

            # get
            full_diff = self.repo.git.diff(parent_hash, gt_commit)

            from modules.diff_filter import DiffFilter
            diff_filter = DiffFilter()
            source_diff, test_diff, stats = diff_filter.filter_test_changes(full_diff)

            return {
                'parent_hash': parent_hash,
                'source_only_diff': source_diff
            }

        except Exception as e:
            logger.error(f"generateV-0.5informationFailed: {e}")
            return None

    def _get_next_task_id(self) -> int:
        
        import re

        max_id = 0
        pattern = re.compile(rf'^eval/{re.escape(self.project_name)}-task_(\d+)$')

        try:
            # get
            branches = self.repo.git.branch('-a').split('\n')

            for branch in branches:
                branch = branch.strip().lstrip('* ')
                # process
                if branch.startswith('remotes/origin/'):
                    branch = branch[len('remotes/origin/'):]

                match = pattern.match(branch)
                if match:
                    task_id = int(match.group(1))
                    max_id = max(max_id, task_id)

        except Exception as e:
            logger.debug(f"branchFailed: {e}")

        return max_id + 1

    def _get_worktree_path(self, task_id: int) -> str:
        """generateworktree path"""
        return os.path.join(
            self.eval_dir,
            f"{self.project_name}-task_{task_id:03d}_eval"
        )

    def _create_worktree(self, commit_hash: str, worktree_path: str) -> bool:
        """creategit worktree"""
        try:
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path)

            self.repo.git.worktree('add', '--detach', worktree_path, commit_hash)
            logger.debug(f"createworktree: {worktree_path}")
            return True

        except GitCommandError as e:
            logger.error(f"createworktreeFailed: {e}")
            return False

    def _apply_patch(self, patch_content: str, worktree_path: str) -> Dict[str, Any]:
        
        result = {'success': False}

        if not patch_content or not patch_content.strip():
            result['success'] = True
            result['message'] = "Empty patch, nothing to apply"
            return result

        patch_file = os.path.join(worktree_path, '.tubench_patch.diff')

        try:
            if not patch_content.endswith('\n'):
                patch_content = patch_content + '\n'

            with open(patch_file, 'w', encoding='utf-8') as f:
                f.write(patch_content)

            process = subprocess.run(
                ['git', 'apply', '--verbose', patch_file],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=60
            )

            if process.returncode == 0:
                result['success'] = True
            else:
                process2 = subprocess.run(
                    ['git', 'apply', '--3way', patch_file],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if process2.returncode == 0:
                    result['success'] = True
                else:
                    result['error'] = process.stderr or process2.stderr

        except subprocess.TimeoutExpired:
            result['error'] = "Patch application timed out"
        except Exception as e:
            result['error'] = str(e)
        finally:
            if os.path.exists(patch_file):
                try:
                    os.remove(patch_file)
                except:
                    pass

        return result

    def _cleanup_worktree(self, worktree_path: str) -> bool:
        """clean upworktree"""
        try:
            if os.path.exists(worktree_path):
                try:
                    self.repo.git.worktree('remove', '--force', worktree_path)
                except:
                    pass

                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)

                logger.debug(f"clean upworktree: {worktree_path}")
                return True

        except Exception as e:
            logger.warning(f"clean upworktreefail {worktree_path}: {e}")

        return False
