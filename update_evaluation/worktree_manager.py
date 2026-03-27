"""
Worktree manager - creates and manages isolated working environments for evaluation tasks
"""

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
        # 必须包含 --- 和 +++ 行才是有效文本 patch
        if not (re.search(r'^--- ', sec, re.MULTILINE) and
                re.search(r'^\+\+\+ ', sec, re.MULTILINE)):
            continue
        result_sections.append(sec)
    return ''.join(result_sections)


class WorktreeManager:
    """Worktree管理器 - 管理evaluate用的isolated工作environment"""

    # defaultevaluateworktreedirectory
    DEFAULT_EVAL_DIR = "/tmp/tubench_eval"

    def __init__(self, repo_path: str, eval_dir: str = None):
        """
        initializeWorktree管理器

        Args:
            repo_path: 原始repository path
            eval_dir: evaluateworktree的基础directory
        """
        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        self.repo = Repo(repo_path)
        self.eval_dir = eval_dir or self.DEFAULT_EVAL_DIR

        # 确保evaluatedirectory存in
        os.makedirs(self.eval_dir, exist_ok=True)

    def prepare_evaluation_worktree(self,
                                     gt_commit: str,
                                     cache_dir: str = None) -> Dict[str, Any]:
        """
        为evaluation tasks准备worktree

        流程：
        1. get V-0.5 information（parent commit + source_only_diff）
        2. createevaluatebranch eval/<gt_commit_short>
        3. inbranch上应用 source_only_diff 并commit，形成 V-0.5 commit
        4. 基于 V-0.5 commit create worktree

        Args:
            gt_commit: GT commit hash (V0)
            cache_dir: cache directory，用于读取V-0.5information

        Returns:
            dict: {
                'success': bool,
                'worktree_path': str,
                'v05_commit': str,  # V-0.5 的 commit hash
                'v05_branch': str,  # V-0.5 的branch名
                'parent_commit': str,  # parent commit (V-1)
                'gt_commit': str,
                'error': str
            }
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
            # 1. getV-0.5information（从cache或实时generate）
            v05_info = self._get_v05_info(gt_commit, cache_dir)
            if not v05_info:
                result['error'] = f"无法getcommit {gt_commit[:8]} 的V-0.5information"
                return result

            parent_hash = v05_info.get('parent_hash')
            source_only_diff = v05_info.get('source_only_diff')

            if not parent_hash:
                result['error'] = f"commit {gt_commit[:8]} 没有父commit"
                return result

            result['parent_commit'] = parent_hash

            # 2. generatetask序号和branch名
            task_id = self._get_next_task_id()
            branch_name = f"eval/{self.project_name}-task_{task_id:03d}"

            # 3. create V-0.5 branch并commit
            v05_commit = self._create_v05_branch(
                parent_hash, source_only_diff, branch_name, gt_commit
            )

            if not v05_commit:
                result['error'] = "createV-0.5branchfail"
                return result

            result['v05_commit'] = v05_commit
            result['v05_branch'] = branch_name
            result['task_id'] = task_id

            # 4. createworktreepath
            worktree_path = self._get_worktree_path(task_id)

            # 5. 如果已存in，先clean up
            if os.path.exists(worktree_path):
                self._cleanup_worktree(worktree_path)

            # 6. 基于 V-0.5 commit create worktree
            if not self._create_worktree(v05_commit, worktree_path):
                result['error'] = "createworktreefail"
                return result

            result['success'] = True
            result['worktree_path'] = worktree_path

            logger.info(f"✓ createevaluateworktree: {worktree_path}")
            logger.info(f"✓ V-0.5branch: {branch_name} ({v05_commit[:8]})")
            logger.info(f"✓ 基于parent: {parent_hash[:8]}")

        except Exception as e:
            logger.error(f"准备evaluateworktreeFailed: {e}")
            result['error'] = str(e)

        return result

    def _create_v05_branch(self,
                           parent_hash: str,
                           source_only_diff: str,
                           branch_name: str,
                           gt_commit: str) -> Optional[str]:
        """
        create V-0.5 branch并commit

        Args:
            parent_hash: parent commit hash
            source_only_diff: source code diff
            branch_name: branch名
            gt_commit: GT commit hash（用于get原始 commit message）

        Returns:
            str: V-0.5 commit hash，failreturn None
        """

        # save当前状态
        original_head = self.repo.head.commit.hexsha
        original_branch = None
        try:
            original_branch = self.repo.active_branch.name
        except TypeError:
            pass  # detached HEAD

        try:
            # 1. delete已存in的同名branch
            try:
                self.repo.git.branch('-D', branch_name)
                logger.debug(f"delete已存in的branch: {branch_name}")
            except GitCommandError:
                pass

            # 2. 从 parent commit create新branch
            self.repo.git.checkout('-b', branch_name, parent_hash)
            logger.debug(f"createbranch {branch_name} 基于 {parent_hash[:8]}")

            # 3. 应用 source_only_diff
            if source_only_diff and source_only_diff.strip():
                # 写入临时 patch file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                    if not source_only_diff.endswith('\n'):
                        source_only_diff += '\n'
                    f.write(source_only_diff)
                    patch_file = f.name

                try:
                    # 尝试1: 标准应用，忽略空白符warning
                    process = subprocess.run(
                        ['git', 'apply', '--whitespace=nowarn', patch_file],
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if process.returncode != 0:
                        # 尝试2: --3way 模式（应对缺失blob的情况）
                        process = subprocess.run(
                            ['git', 'apply', '--3way', '--whitespace=nowarn', patch_file],
                            cwd=self.repo_path,
                            capture_output=True,
                            text=True,
                            timeout=60
                        )

                    if process.returncode != 0:
                        # 尝试3: 排除二进制file后重新应用
                        binary_err = (
                            'cannot apply binary patch' in process.stderr
                            or 'lacks the necessary blob' in process.stderr
                        )
                        if binary_err:
                            # 过滤掉二进制file的 patch 段落，只保留文本file部分
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
                                            f"已skip二进制file，仅应用文本变更"
                                        )
                                finally:
                                    if os.path.exists(text_patch_file):
                                        os.remove(text_patch_file)

                    if process.returncode != 0:
                        logger.error(f"应用patchFailed: {process.stderr}")
                        return None

                finally:
                    if os.path.exists(patch_file):
                        os.remove(patch_file)

                # 4. commit变更（只commitsource code变更，不添加额外file）
                self.repo.git.add('-A')

                if self.repo.is_dirty():
                    # get原始 GT commit 的 message
                    gt_commit_obj = self.repo.commit(gt_commit)
                    original_message = gt_commit_obj.message.strip()

                    # 构建新的 commit message：原始 message + description
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
        """
        commit用户inworktree中的修改

        Args:
            worktree_path: worktreepath
            message: commit message

        Returns:
            dict: {
                'success': bool,
                'user_commit': str,
                'changed_files': list,
                'error': str
            }
        """
        result = {
            'success': False,
            'user_commit': None,
            'changed_files': [],
            'error': None
        }

        try:
            worktree_repo = Repo(worktree_path)

            # check是否有变更
            if not worktree_repo.is_dirty() and not worktree_repo.untracked_files:
                result['error'] = "没有detect到任何修改"
                return result

            # get变更的file
            changed_files = []
            for item in worktree_repo.index.diff(None):
                changed_files.append(item.a_path)
            changed_files.extend(worktree_repo.untracked_files)
            result['changed_files'] = changed_files

            # 添加所有变更
            worktree_repo.git.add('-A')

            # commit
            if not message:
                message = f"[TUBench Evaluation] User test modification"

            worktree_repo.git.commit('-m', message)

            result['success'] = True
            result['user_commit'] = worktree_repo.head.commit.hexsha

            logger.info(f"✓ 用户修改已commit: {result['user_commit'][:8]}")

        except Exception as e:
            logger.error(f"commit用户修改Failed: {e}")
            result['error'] = str(e)

        return result

    def get_worktree_info(self, worktree_path: str) -> Optional[Dict[str, Any]]:
        """
        getworktree的information（从gitinformation中parse）

        Args:
            worktree_path: worktreepath

        Returns:
            dict: worktreeinformation，包含 v05_commit, parent_commit, task_id 等
        """
        try:
            from git import Repo
            import re

            worktree_repo = Repo(worktree_path)

            # get当前 HEAD commit (V-0.5)
            v05_commit = worktree_repo.head.commit.hexsha

            # get parent commit（V-0.5 的 parent 就是 V-1）
            parent_commit = None
            if worktree_repo.head.commit.parents:
                parent_commit = worktree_repo.head.commit.parents[0].hexsha

            # 从 worktree path名parse task_id
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
        """
        clean upworktree

        Args:
            worktree_path: worktreepath

        Returns:
            bool: 是否success
        """
        return self._cleanup_worktree(worktree_path)

    def cleanup_all_worktrees(self) -> int:
        """
        clean up所有evaluateworktree

        Returns:
            int: clean up的worktree数量
        """
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

        logger.info(f"clean up了 {count} 个evaluateworktree")
        return count

    def _get_v05_info(self, gt_commit: str, cache_dir: str = None) -> Optional[Dict]:
        """getV-0.5versioninformation（从cache或实时generate）"""
        # 尝试从cache读取
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
                    logger.debug(f"读取cacheFailed: {e}")

        # 实时generate
        return self._generate_v05_info(gt_commit)

    def _generate_v05_info(self, gt_commit: str) -> Optional[Dict]:
        """实时generateV-0.5information"""
        try:
            commit = self.repo.commit(gt_commit)
            if not commit.parents:
                return None

            parent_hash = commit.parents[0].hexsha

            # get完整diff
            full_diff = self.repo.git.diff(parent_hash, gt_commit)

            # 分离source code和test code的diff
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
        """
        get下一个可用的task序号

        通过扫描现有的 eval/{project}-task_* branch来确定
        """
        import re

        max_id = 0
        pattern = re.compile(rf'^eval/{re.escape(self.project_name)}-task_(\d+)$')

        try:
            # get所有branch
            branches = self.repo.git.branch('-a').split('\n')

            for branch in branches:
                branch = branch.strip().lstrip('* ')
                # process远程branch前缀
                if branch.startswith('remotes/origin/'):
                    branch = branch[len('remotes/origin/'):]

                match = pattern.match(branch)
                if match:
                    task_id = int(match.group(1))
                    max_id = max(max_id, task_id)

        except Exception as e:
            logger.debug(f"扫描branchFailed: {e}")

        return max_id + 1

    def _get_worktree_path(self, task_id: int) -> str:
        """generateworktreepath"""
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
        """应用patch到worktree"""
        result = {'success': False}

        if not patch_content or not patch_content.strip():
            result['success'] = True
            result['message'] = "Empty patch, nothing to apply"
            return result

        patch_file = os.path.join(worktree_path, '.tubench_patch.diff')

        try:
            # 确保patch以换行结尾
            if not patch_content.endswith('\n'):
                patch_content = patch_content + '\n'

            with open(patch_file, 'w', encoding='utf-8') as f:
                f.write(patch_content)

            # 应用patch
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
                # 尝试使用 --3way
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
                # 先尝试用git命令delete
                try:
                    self.repo.git.worktree('remove', '--force', worktree_path)
                except:
                    pass

                # 如果还存in，强制deletedirectory
                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)

                logger.debug(f"clean upworktree: {worktree_path}")
                return True

        except Exception as e:
            logger.warning(f"clean upworktreefail {worktree_path}: {e}")

        return False
