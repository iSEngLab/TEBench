"""
Filtered version generator - responsible for generating the V-0.5 version that hides test changes
"""

import os
import tempfile
from git import GitCommandError
from config import Config
from utils.logger import get_logger
from .diff_filter import DiffFilter

logger = get_logger()


class FilteredVersionGenerator:
    """Filtered version generator - generates source-only or test-only change versions"""

    MODE_SOURCE_ONLY = "source_only"
    MODE_TEST_ONLY = "test_only"

    def __init__(self, git_analyzer):
        """
        Initialize the filtered version generator

        Args:
            git_analyzer: GitAnalyzer instance
        """
        self.git_analyzer = git_analyzer
        self.diff_filter = DiffFilter()
        self.repo = git_analyzer.repo
    
    def generate_filtered_version(self, commit_info):
        """
        generate filtered version (V-0.5, source code changes only)
        """
        result = self._generate_version(commit_info, mode=self.MODE_SOURCE_ONLY)
        return {
            'success': result['success'],
            'filtered_commit_hash': result.get('commit_hash'),
            'branch_name': result.get('branch_name'),
            'test_changes_hidden': result.get('hidden_changes', {}),
            'stats': result.get('stats', {}),
            'error': result.get('error')
        }
    
    def generate_test_only_version(self, commit_info):
        """
        generate test-only version (T-0.5, test code changes only)
        """
        result = self._generate_version(commit_info, mode=self.MODE_TEST_ONLY)
        return {
            'success': result['success'],
            'test_only_commit_hash': result.get('commit_hash'),
            'branch_name': result.get('branch_name'),
            'source_changes_hidden': result.get('hidden_changes', {}),
            'stats': result.get('stats', {}),
            'error': result.get('error')
        }
    
    def _generate_version(self, commit_info, mode):
        """
        generate version in the specified mode
        
        Args:
            commit_info: commit information dictionary
            mode: generation mode (source_only/test_only)
            
        Returns:
            dict: {
                'success': bool,
                'commit_hash': str,
                'branch_name': str,
                'hidden_changes': dict,
                'stats': dict,
                'error': str
            }
        """
        result = {
            'success': False,
            'commit_hash': None,
            'branch_name': None,
            'hidden_changes': {},
            'stats': {},
            'error': None
        }
        
        try:
            commit_hash = commit_info['commit_hash']
            parent_hash = commit_info['parent_hash']
            
            if not parent_hash:
                result['error'] = "no parent commit, cannot generate version"
                return result
            
            if mode not in (self.MODE_SOURCE_ONLY, self.MODE_TEST_ONLY):
                result['error'] = f"unknown generation mode: {mode}"
                return result
            
            # 1. Get the full diff (using git command to get standard format)
            try:
                diff_text = self.repo.git.diff(parent_hash, commit_hash)
            except Exception as e:
                logger.error(f"getdiffFailed: {e}")
                result['error'] = f"getdiffFailed: {e}"
                return result
            
            # 2. 过滤diff，分离source code和test code变更
            filtered_diff, test_diff, filter_stats = self.diff_filter.filter_test_changes(diff_text)
            selected_diff, hidden_diff = self._select_diff(filtered_diff, test_diff, mode)
            
            if not selected_diff:
                result['error'] = "选定的diff为空，无法generateversion"
                return result
            
            # 3. get原始commit的完整message
            original_commit = self.repo.commit(commit_hash)
            original_message = original_commit.message.strip()
            
            # 4. create新branch并应用diff
            branch_name = self._build_branch_name(commit_hash, mode)
            commit_message = self._build_commit_message(original_message, mode)
            new_hash = self._apply_diff_to_branch(
                parent_hash,
                selected_diff,
                branch_name,
                commit_message
            )
            
            if not new_hash:
                result['error'] = "应用difffail"
                return result
            
            # 5. validate可compile性
            if not self._verify_compilable(new_hash):
                result['error'] = "generate的version无法compile"
                # clean upbranch
                self._cleanup_branch(branch_name)
                return result
            
            # 6. 提取被隐藏的变更information
            hidden_changes_info = self.diff_filter.extract_changes_info(hidden_diff)
            
            # 7. returnsuccessresult
            result['success'] = True
            result['commit_hash'] = new_hash
            result['branch_name'] = branch_name
            result['hidden_changes'] = hidden_changes_info
            result['stats'] = filter_stats
            
            logger.info(f"successgenerateversion: {new_hash[:8]} (branch: {branch_name}, 模式: {mode})")
            
        except Exception as e:
            logger.error(f"generateversionfail [{commit_info.get('commit_hash', 'unknown')[:8]}]: {e}")
            result['error'] = str(e)
        
        return result
    
    def _apply_diff_to_branch(self, parent_hash, diff_text, branch_name, commit_message):
        """
        应用diff到新branch
        
        Args:
            parent_hash: 父commit的hash
            diff_text: diff文本
            branch_name: 新branch名称
            commit_message: commit message
            
        Returns:
            str: 新commit的hash，failreturnNone
        """
        try:
            # 1. 彻底clean up工作区，确保完全干净的状态
            logger.debug(f"clean up工作区...")
            self.repo.git.reset('--hard', 'HEAD')
            self.repo.git.clean('-fd')  # delete未跟踪的file和directory
            
            # 2. delete已存in的同名branch
            try:
                self.repo.git.branch('-D', branch_name)
                logger.debug(f"已delete旧branch: {branch_name}")
            except GitCommandError:
                pass  # branch不存in，忽略
            
            # 3. 从父commitcreate新branch
            self.repo.git.checkout('-b', branch_name, parent_hash)
            
            # 4. 再次确保branch状态干净（移除可能的target/等compile产物）
            self.repo.git.reset('--hard', parent_hash)
            self.repo.git.clean('-fd')
            logger.debug(f"已create并clean upbranch: {branch_name}")
            
            # 将diffsave到临时file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(diff_text)
                patch_file = f.name
            
            try:
                # 应用patch
                self.repo.git.apply(patch_file, '--whitespace=nowarn')
                
                # 添加变更到暂存区
                self.repo.git.add('-A')
                
                # check是否有变更需要commit
                if self.repo.is_dirty():
                    self.repo.git.commit('-m', commit_message)
                    
                    # get新commit的hash
                    new_commit_hash = self.repo.head.commit.hexsha
                    
                    logger.debug(f"success应用filtered diff，新commit: {new_commit_hash[:8]}")
                    return new_commit_hash
                else:
                    logger.warning("应用patch后没有变更")
                    return None
                
            finally:
                # clean up临时file
                if os.path.exists(patch_file):
                    os.remove(patch_file)
        
        except GitCommandError as e:
            logger.error(f"应用diffFailed: {e}")
            return None
        
        except Exception as e:
            logger.error(f"应用diff异常: {e}")
            return None

    def _select_diff(self, filtered_diff, test_diff, mode):
        """
        根据模式选择需要应用的diff以及隐藏的diff
        """
        if mode == self.MODE_SOURCE_ONLY:
            return filtered_diff, test_diff
        if mode == self.MODE_TEST_ONLY:
            return test_diff, filtered_diff
        return "", ""
    
    def _build_branch_name(self, commit_hash, mode):
        """
        构建branch名称
        """
        prefix = "filtered" if mode == self.MODE_SOURCE_ONLY else "test-only"
        return f"{prefix}/{commit_hash[:8]}"
    
    def _build_commit_message(self, original_message, mode):
        """
        构建commitinformation
        """
        if mode == self.MODE_SOURCE_ONLY:
            suffix = "[Filtered Version - Source Code Changes Only]"
        else:
            suffix = "[Test-Only Version - Test Code Changes Only]"
        return f"{original_message}\n\n{suffix}"
    
    def _verify_compilable(self, commit_hash):
        """
        validate指定commit是否可compile
        
        Args:
            commit_hash: commit的hash
            
        Returns:
            bool: 是否可compile
        """
        try:
            # 切换到该commit并确保工作区干净
            self.repo.git.checkout(commit_hash)
            self.repo.git.reset('--hard')
            self.repo.git.clean('-fd')  # clean upcompile前的状态
            
            # 确保工作区干净
            self.repo.git.reset('--hard', commit_hash)
            self.repo.git.clean('-fd')
            
            # check是否有pom.xml
            pom_path = os.path.join(self.repo.working_dir, 'pom.xml')
            if not os.path.exists(pom_path):
                logger.warning(f"未foundpom.xml，skipcompilevalidate")
                return True  # 假设可以compile
            
            # 尝试compile
            from .maven_executor import MavenExecutor
            maven = MavenExecutor(self.repo.working_dir)
            success, _ = maven._run_maven_command('clean compile -DskipTests')
            
            # compilevalidate后，clean upcompile产物，确保branch干净
            if success:
                logger.debug("compilesuccess，clean upcompile产物...")
                target_dir = os.path.join(self.repo.working_dir, 'target')
                if os.path.exists(target_dir):
                    import shutil
                    shutil.rmtree(target_dir)
                    logger.debug(f"已deletetargetdirectory")
            
            return success
        
        except Exception as e:
            logger.error(f"validatecompileFailed: {e}")
            return False
    
    def _cleanup_branch(self, branch_name):
        """
        clean upcreate的branch
        
        Args:
            branch_name: branch名称
        """
        try:
            # 切换回主branch
            self.repo.git.checkout('HEAD', '--detach')
            # deletebranch
            self.repo.git.branch('-D', branch_name)
            logger.debug(f"已clean upbranch: {branch_name}")
        except Exception as e:
            logger.warning(f"clean upbranchfail [{branch_name}]: {e}")
    
    def restore_original_branch(self):
        """恢复到原始branch/状态"""
        try:
            # 切换回HEAD
            self.repo.git.checkout('HEAD', '--detach')
            logger.debug("已恢复到原始状态")
        except Exception as e:
            logger.warning(f"restore original stateFailed: {e}")
