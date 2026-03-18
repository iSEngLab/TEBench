"""
Worktree管理器 - 为评估任务创建和管理隔离的工作环境
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
    从 unified diff 中移除二进制文件的 patch 段落，仅保留可文本应用的部分。

    二进制 patch 段落的特征：
      - 包含 "GIT binary patch" 行，或
      - diff header 后紧跟 "Binary files ... differ"，或
      - index 行后没有 --- / +++ 行（无法作为文本 patch 应用）
    """
    result_sections = []
    # 按 "diff --git" 分割
    sections = re.split(r'(?=^diff --git )', patch, flags=re.MULTILINE)
    for sec in sections:
        if not sec.strip():
            continue
        # 跳过二进制段落
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
    """Worktree管理器 - 管理评估用的隔离工作环境"""

    # 默认评估worktree目录
    DEFAULT_EVAL_DIR = "/tmp/tubench_eval"

    def __init__(self, repo_path: str, eval_dir: str = None):
        """
        初始化Worktree管理器

        Args:
            repo_path: 原始仓库路径
            eval_dir: 评估worktree的基础目录
        """
        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        self.repo = Repo(repo_path)
        self.eval_dir = eval_dir or self.DEFAULT_EVAL_DIR

        # 确保评估目录存在
        os.makedirs(self.eval_dir, exist_ok=True)

    def prepare_evaluation_worktree(self,
                                     gt_commit: str,
                                     cache_dir: str = None) -> Dict[str, Any]:
        """
        为评估任务准备worktree

        流程：
        1. 获取 V-0.5 信息（parent commit + source_only_diff）
        2. 创建评估分支 eval/<gt_commit_short>
        3. 在分支上应用 source_only_diff 并提交，形成 V-0.5 commit
        4. 基于 V-0.5 commit 创建 worktree

        Args:
            gt_commit: GT commit hash (V0)
            cache_dir: 缓存目录，用于读取V-0.5信息

        Returns:
            dict: {
                'success': bool,
                'worktree_path': str,
                'v05_commit': str,  # V-0.5 的 commit hash
                'v05_branch': str,  # V-0.5 的分支名
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
            # 1. 获取V-0.5信息（从缓存或实时生成）
            v05_info = self._get_v05_info(gt_commit, cache_dir)
            if not v05_info:
                result['error'] = f"无法获取commit {gt_commit[:8]} 的V-0.5信息"
                return result

            parent_hash = v05_info.get('parent_hash')
            source_only_diff = v05_info.get('source_only_diff')

            if not parent_hash:
                result['error'] = f"commit {gt_commit[:8]} 没有父commit"
                return result

            result['parent_commit'] = parent_hash

            # 2. 生成任务序号和分支名
            task_id = self._get_next_task_id()
            branch_name = f"eval/{self.project_name}-task_{task_id:03d}"

            # 3. 创建 V-0.5 分支并提交
            v05_commit = self._create_v05_branch(
                parent_hash, source_only_diff, branch_name, gt_commit
            )

            if not v05_commit:
                result['error'] = "创建V-0.5分支失败"
                return result

            result['v05_commit'] = v05_commit
            result['v05_branch'] = branch_name
            result['task_id'] = task_id

            # 4. 创建worktree路径
            worktree_path = self._get_worktree_path(task_id)

            # 5. 如果已存在，先清理
            if os.path.exists(worktree_path):
                self._cleanup_worktree(worktree_path)

            # 6. 基于 V-0.5 commit 创建 worktree
            if not self._create_worktree(v05_commit, worktree_path):
                result['error'] = "创建worktree失败"
                return result

            result['success'] = True
            result['worktree_path'] = worktree_path

            logger.info(f"✓ 创建评估worktree: {worktree_path}")
            logger.info(f"✓ V-0.5分支: {branch_name} ({v05_commit[:8]})")
            logger.info(f"✓ 基于parent: {parent_hash[:8]}")

        except Exception as e:
            logger.error(f"准备评估worktree失败: {e}")
            result['error'] = str(e)

        return result

    def _create_v05_branch(self,
                           parent_hash: str,
                           source_only_diff: str,
                           branch_name: str,
                           gt_commit: str) -> Optional[str]:
        """
        创建 V-0.5 分支并提交

        Args:
            parent_hash: parent commit hash
            source_only_diff: 源代码 diff
            branch_name: 分支名
            gt_commit: GT commit hash（用于获取原始 commit message）

        Returns:
            str: V-0.5 commit hash，失败返回 None
        """

        # 保存当前状态
        original_head = self.repo.head.commit.hexsha
        original_branch = None
        try:
            original_branch = self.repo.active_branch.name
        except TypeError:
            pass  # detached HEAD

        try:
            # 1. 删除已存在的同名分支
            try:
                self.repo.git.branch('-D', branch_name)
                logger.debug(f"删除已存在的分支: {branch_name}")
            except GitCommandError:
                pass

            # 2. 从 parent commit 创建新分支
            self.repo.git.checkout('-b', branch_name, parent_hash)
            logger.debug(f"创建分支 {branch_name} 基于 {parent_hash[:8]}")

            # 3. 应用 source_only_diff
            if source_only_diff and source_only_diff.strip():
                # 写入临时 patch 文件
                with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                    if not source_only_diff.endswith('\n'):
                        source_only_diff += '\n'
                    f.write(source_only_diff)
                    patch_file = f.name

                try:
                    # 尝试1: 标准应用，忽略空白符警告
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
                        # 尝试3: 排除二进制文件后重新应用
                        binary_err = (
                            'cannot apply binary patch' in process.stderr
                            or 'lacks the necessary blob' in process.stderr
                        )
                        if binary_err:
                            # 过滤掉二进制文件的 patch 段落，只保留文本文件部分
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
                                            f"已跳过二进制文件，仅应用文本变更"
                                        )
                                finally:
                                    if os.path.exists(text_patch_file):
                                        os.remove(text_patch_file)

                    if process.returncode != 0:
                        logger.error(f"应用patch失败: {process.stderr}")
                        return None

                finally:
                    if os.path.exists(patch_file):
                        os.remove(patch_file)

                # 4. 提交变更（只提交源代码变更，不添加额外文件）
                self.repo.git.add('-A')

                if self.repo.is_dirty():
                    # 获取原始 GT commit 的 message
                    gt_commit_obj = self.repo.commit(gt_commit)
                    original_message = gt_commit_obj.message.strip()

                    # 构建新的 commit message：原始 message + 说明
                    commit_message = (
                        f"{original_message}\n\n"
                        f"[Source Code Changes Only]"
                    )
                    self.repo.git.commit('-m', commit_message)

            v05_commit = self.repo.head.commit.hexsha
            logger.debug(f"V-0.5 commit: {v05_commit[:8]}")

            return v05_commit

        except Exception as e:
            logger.error(f"创建V-0.5分支失败: {e}")
            return None

        finally:
            # 恢复原始状态
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
        提交用户在worktree中的修改

        Args:
            worktree_path: worktree路径
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

            # 检查是否有变更
            if not worktree_repo.is_dirty() and not worktree_repo.untracked_files:
                result['error'] = "没有检测到任何修改"
                return result

            # 获取变更的文件
            changed_files = []
            for item in worktree_repo.index.diff(None):
                changed_files.append(item.a_path)
            changed_files.extend(worktree_repo.untracked_files)
            result['changed_files'] = changed_files

            # 添加所有变更
            worktree_repo.git.add('-A')

            # 提交
            if not message:
                message = f"[TUBench Evaluation] User test modification"

            worktree_repo.git.commit('-m', message)

            result['success'] = True
            result['user_commit'] = worktree_repo.head.commit.hexsha

            logger.info(f"✓ 用户修改已提交: {result['user_commit'][:8]}")

        except Exception as e:
            logger.error(f"提交用户修改失败: {e}")
            result['error'] = str(e)

        return result

    def get_worktree_info(self, worktree_path: str) -> Optional[Dict[str, Any]]:
        """
        获取worktree的信息（从git信息中解析）

        Args:
            worktree_path: worktree路径

        Returns:
            dict: worktree信息，包含 v05_commit, parent_commit, task_id 等
        """
        try:
            from git import Repo
            import re

            worktree_repo = Repo(worktree_path)

            # 获取当前 HEAD commit (V-0.5)
            v05_commit = worktree_repo.head.commit.hexsha

            # 获取 parent commit（V-0.5 的 parent 就是 V-1）
            parent_commit = None
            if worktree_repo.head.commit.parents:
                parent_commit = worktree_repo.head.commit.parents[0].hexsha

            # 从 worktree 路径名解析 task_id
            # 路径格式: {project}-task_{id}_eval
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
            logger.debug(f"获取worktree信息失败: {e}")
            return None

    def cleanup_worktree(self, worktree_path: str) -> bool:
        """
        清理worktree

        Args:
            worktree_path: worktree路径

        Returns:
            bool: 是否成功
        """
        return self._cleanup_worktree(worktree_path)

    def cleanup_all_worktrees(self) -> int:
        """
        清理所有评估worktree

        Returns:
            int: 清理的worktree数量
        """
        count = 0
        if os.path.exists(self.eval_dir):
            for name in os.listdir(self.eval_dir):
                path = os.path.join(self.eval_dir, name)
                if os.path.isdir(path) and name.startswith(self.project_name):
                    if self._cleanup_worktree(path):
                        count += 1

        # 执行git worktree prune
        try:
            self.repo.git.worktree('prune')
        except:
            pass

        logger.info(f"清理了 {count} 个评估worktree")
        return count

    def _get_v05_info(self, gt_commit: str, cache_dir: str = None) -> Optional[Dict]:
        """获取V-0.5版本信息（从缓存或实时生成）"""
        # 尝试从缓存读取
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
                    logger.debug(f"读取缓存失败: {e}")

        # 实时生成
        return self._generate_v05_info(gt_commit)

    def _generate_v05_info(self, gt_commit: str) -> Optional[Dict]:
        """实时生成V-0.5信息"""
        try:
            commit = self.repo.commit(gt_commit)
            if not commit.parents:
                return None

            parent_hash = commit.parents[0].hexsha

            # 获取完整diff
            full_diff = self.repo.git.diff(parent_hash, gt_commit)

            # 分离源代码和测试代码的diff
            from modules.diff_filter import DiffFilter
            diff_filter = DiffFilter()
            source_diff, test_diff, stats = diff_filter.filter_test_changes(full_diff)

            return {
                'parent_hash': parent_hash,
                'source_only_diff': source_diff
            }

        except Exception as e:
            logger.error(f"生成V-0.5信息失败: {e}")
            return None

    def _get_next_task_id(self) -> int:
        """
        获取下一个可用的任务序号

        通过扫描现有的 eval/{project}-task_* 分支来确定
        """
        import re

        max_id = 0
        pattern = re.compile(rf'^eval/{re.escape(self.project_name)}-task_(\d+)$')

        try:
            # 获取所有分支
            branches = self.repo.git.branch('-a').split('\n')

            for branch in branches:
                branch = branch.strip().lstrip('* ')
                # 处理远程分支前缀
                if branch.startswith('remotes/origin/'):
                    branch = branch[len('remotes/origin/'):]

                match = pattern.match(branch)
                if match:
                    task_id = int(match.group(1))
                    max_id = max(max_id, task_id)

        except Exception as e:
            logger.debug(f"扫描分支失败: {e}")

        return max_id + 1

    def _get_worktree_path(self, task_id: int) -> str:
        """生成worktree路径"""
        return os.path.join(
            self.eval_dir,
            f"{self.project_name}-task_{task_id:03d}_eval"
        )

    def _create_worktree(self, commit_hash: str, worktree_path: str) -> bool:
        """创建git worktree"""
        try:
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path)

            self.repo.git.worktree('add', '--detach', worktree_path, commit_hash)
            logger.debug(f"创建worktree: {worktree_path}")
            return True

        except GitCommandError as e:
            logger.error(f"创建worktree失败: {e}")
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
        """清理worktree"""
        try:
            if os.path.exists(worktree_path):
                # 先尝试用git命令删除
                try:
                    self.repo.git.worktree('remove', '--force', worktree_path)
                except:
                    pass

                # 如果还存在，强制删除目录
                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)

                logger.debug(f"清理worktree: {worktree_path}")
                return True

        except Exception as e:
            logger.warning(f"清理worktree失败 {worktree_path}: {e}")

        return False
