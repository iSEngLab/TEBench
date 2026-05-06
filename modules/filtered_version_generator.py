"""Module."""

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
            
            # 2.
            filtered_diff, test_diff, filter_stats = self.diff_filter.filter_test_changes(diff_text)
            selected_diff, hidden_diff = self._select_diff(filtered_diff, test_diff, mode)
            
            if not selected_diff:
                result['error'] = "diff，generateversion"
                return result
            
            # 3. get
            original_commit = self.repo.commit(commit_hash)
            original_message = original_commit.message.strip()
            
            # 4. create
            branch_name = self._build_branch_name(commit_hash, mode)
            commit_message = self._build_commit_message(original_message, mode)
            new_hash = self._apply_diff_to_branch(
                parent_hash,
                selected_diff,
                branch_name,
                commit_message
            )
            
            if not new_hash:
                result['error'] = "difffail"
                return result
            
            # 5. validate
            if not self._verify_compilable(new_hash):
                result['error'] = "generateversioncompile"
                # clean upbranch
                self._cleanup_branch(branch_name)
                return result
            
            # 6.
            hidden_changes_info = self.diff_filter.extract_changes_info(hidden_diff)
            
            # 7. returnsuccessresult
            result['success'] = True
            result['commit_hash'] = new_hash
            result['branch_name'] = branch_name
            result['hidden_changes'] = hidden_changes_info
            result['stats'] = filter_stats
            
            logger.info(f"successgenerateversion: {new_hash[:8]} (branch: {branch_name}, : {mode})")
            
        except Exception as e:
            logger.error(f"generateversionfail [{commit_info.get('commit_hash', 'unknown')[:8]}]: {e}")
            result['error'] = str(e)
        
        return result
    
    def _apply_diff_to_branch(self, parent_hash, diff_text, branch_name, commit_message):
        """Args:
            commit_message: commit message
"""
        try:
            # 1.
            logger.debug(f"clean up...")
            self.repo.git.reset('--hard', 'HEAD')
            self.repo.git.clean('-fd')  # delete
            
            # 2. delete
            try:
                self.repo.git.branch('-D', branch_name)
                logger.debug(f"deletebranch: {branch_name}")
            except GitCommandError:
                pass  # branch
            
            # 3.
            self.repo.git.checkout('-b', branch_name, parent_hash)
            
            # 4.
            self.repo.git.reset('--hard', parent_hash)
            self.repo.git.clean('-fd')
            logger.debug(f"createclean upbranch: {branch_name}")
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
                f.write(diff_text)
                patch_file = f.name
            
            try:
                self.repo.git.apply(patch_file, '--whitespace=nowarn')
                
                self.repo.git.add('-A')
                
                # check
                if self.repo.is_dirty():
                    self.repo.git.commit('-m', commit_message)
                    
                    # get
                    new_commit_hash = self.repo.head.commit.hexsha
                    
                    logger.debug(f"successfiltered diff，commit: {new_commit_hash[:8]}")
                    return new_commit_hash
                else:
                    logger.warning("patch")
                    return None
                
            finally:
                # clean up
                if os.path.exists(patch_file):
                    os.remove(patch_file)
        
        except GitCommandError as e:
            logger.error(f"diffFailed: {e}")
            return None
        
        except Exception as e:
            logger.error(f"diff: {e}")
            return None

    def _select_diff(self, filtered_diff, test_diff, mode):
        
        if mode == self.MODE_SOURCE_ONLY:
            return filtered_diff, test_diff
        if mode == self.MODE_TEST_ONLY:
            return test_diff, filtered_diff
        return "", ""
    
    def _build_branch_name(self, commit_hash, mode):
        
        prefix = "filtered" if mode == self.MODE_SOURCE_ONLY else "test-only"
        return f"{prefix}/{commit_hash[:8]}"
    
    def _build_commit_message(self, original_message, mode):
        
        if mode == self.MODE_SOURCE_ONLY:
            suffix = "[Filtered Version - Source Code Changes Only]"
        else:
            suffix = "[Test-Only Version - Test Code Changes Only]"
        return f"{original_message}\n\n{suffix}"
    
    def _verify_compilable(self, commit_hash):

        try:
            self.repo.git.checkout(commit_hash)
            self.repo.git.reset('--hard')
            self.repo.git.clean('-fd')  # clean upcompile
            
            self.repo.git.reset('--hard', commit_hash)
            self.repo.git.clean('-fd')
            
            # check
            pom_path = os.path.join(self.repo.working_dir, 'pom.xml')
            if not os.path.exists(pom_path):
                logger.warning(f"foundpom.xml，skipcompilevalidate")
                return True
            
            from .maven_executor import MavenExecutor
            maven = MavenExecutor(self.repo.working_dir)
            success, _ = maven._run_maven_command('clean compile -DskipTests')
            
            # compilevalidate
            if success:
                logger.debug("compilesuccess，clean upcompile...")
                target_dir = os.path.join(self.repo.working_dir, 'target')
                if os.path.exists(target_dir):
                    import shutil
                    shutil.rmtree(target_dir)
                    logger.debug(f"deletetargetdirectory")
            
            return success
        
        except Exception as e:
            logger.error(f"validatecompileFailed: {e}")
            return False
    
    def _cleanup_branch(self, branch_name):

        try:
            self.repo.git.checkout('HEAD', '--detach')
            # deletebranch
            self.repo.git.branch('-D', branch_name)
            logger.debug(f"clean upbranch: {branch_name}")
        except Exception as e:
            logger.warning(f"clean upbranchfail [{branch_name}]: {e}")
    
    def restore_original_branch(self):
        
        try:
            self.repo.git.checkout('HEAD', '--detach')
            logger.debug("")
        except Exception as e:
            logger.warning(f"restore original stateFailed: {e}")
