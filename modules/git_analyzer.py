"""
Git analysis module - responsible for extracting commits, diff analysis, and other Git operations
"""

import os
from datetime import datetime
from git import Repo, GitCommandError
from config import Config
from utils.logger import get_logger
from utils.exceptions import RepositoryError, GitOperationError

logger = get_logger()


class GitAnalyzer:
    """Git repository analyzer"""

    def __init__(self, repo_path):
        """
        Initialize the Git analyzer

        Args:
            repo_path: Git repository path
        """
        self.repo_path = repo_path
        try:
            self.repo = Repo(repo_path)
            logger.info(f"Successfully loaded Git repository: {repo_path}")
        except Exception as e:
            logger.error(f"Failed to load Git repository: {e}")
            raise RepositoryError(f"Unable to load Git repository: {repo_path}", {"original_error": str(e)})
    
    def get_all_commits(self, since_date=None, branch='HEAD'):
        """
        Get all commits

        Args:
            since_date: Start date (datetime object)
            branch: Branch name

        Returns:
            list: List of commit objects
        """
        try:
            commits = list(self.repo.iter_commits(branch))
            logger.info(f"Found {len(commits)} commits in total")

            # Date filter
            if since_date:
                commits = [c for c in commits if datetime.fromtimestamp(c.committed_date) >= since_date]
                logger.info(f"{len(commits)} commits remaining after date filter")

            return commits
        except Exception as e:
            logger.error(f"Failed to get commits: {e}")
            return []
    
    def get_commit_info(self, commit):
        """
        Get basic commit information

        Args:
            commit: commit object

        Returns:
            dict: commit information dictionary
        """
        try:
            parent_hash = commit.parents[0].hexsha if commit.parents else None

            return {
                'commit_hash': commit.hexsha,
                'parent_hash': parent_hash,
                'author': str(commit.author),
                'date': datetime.fromtimestamp(commit.committed_date).strftime('%Y-%m-%d %H:%M:%S'),
                'message': commit.message.strip()
            }
        except Exception as e:
            logger.error(f"Failed to get commit information [{commit.hexsha}]: {e}")
            return None
    
    def get_changed_files(self, commit):
        """
        Get the list of files changed in a commit

        Args:
            commit: commit object

        Returns:
            dict: {'test_files': [], 'source_files': [], 'other_files': []}
        """
        try:
            if not commit.parents:
                logger.debug(f"Commit {commit.hexsha} has no parent commit, skipping")
                return {'test_files': [], 'source_files': [], 'other_files': []}

            parent = commit.parents[0]
            diffs = parent.diff(commit)

            test_files = []
            source_files = []
            other_files = []

            for diff in diffs:
                # Get file path (new file or modified file)
                file_path = diff.b_path if diff.b_path else diff.a_path

                if not file_path or not file_path.endswith('.java'):
                    continue

                # Classify files
                if self._is_test_file(file_path):
                    test_files.append(file_path)
                elif self._is_source_file(file_path):
                    source_files.append(file_path)
                else:
                    other_files.append(file_path)

            return {
                'test_files': test_files,
                'source_files': source_files,
                'other_files': other_files
            }

        except Exception as e:
            logger.error(f"Failed to get changed files [{commit.hexsha}]: {e}")
            return {'test_files': [], 'source_files': [], 'other_files': []}
    
    def get_file_diff(self, commit, file_path):
        """
        Get the diff content for a specific file

        Args:
            commit: commit object
            file_path: file path

        Returns:
            str: diff text content (unified diff format)
        """
        try:
            if not commit.parents:
                return ""

            parent = commit.parents[0]

            # Use git command to generate a complete unified diff format (including file headers)
            # so that the unidiff library can parse it correctly
            diff_text = self.repo.git.diff(
                parent.hexsha,
                commit.hexsha,
                '--',
                file_path,
                unified=3  # number of context lines
            )

            return diff_text

        except Exception as e:
            logger.error(f"Failed to get file diff [{file_path}]: {e}")
            return ""
    
    def get_file_content(self, commit_hash, file_path):
        """
        Get the content of a file at a specific commit

        Args:
            commit_hash: commit hash value
            file_path: file path

        Returns:
            str: file content
        """
        try:
            commit = self.repo.commit(commit_hash)
            blob = commit.tree / file_path
            return blob.data_stream.read().decode('utf-8', errors='ignore')
        except Exception as e:
            logger.debug(f"Failed to get file content [{commit_hash}:{file_path}]: {e}")
            return None
    
    def create_worktree(self, commit_hash, worktree_path):
        """
        Create a temporary worktree

        Args:
            commit_hash: commit hash value
            worktree_path: worktree path

        Returns:
            bool: whether successful
        """
        try:
            # Remove existing worktree path if it exists
            if os.path.exists(worktree_path):
                self.remove_worktree(worktree_path)

            # Create worktree
            self.repo.git.worktree('add', worktree_path, commit_hash)
            logger.debug(f"Created worktree: {worktree_path} @ {commit_hash[:8]}")
            return True

        except Exception as e:
            logger.error(f"Failed to create worktree [{commit_hash}]: {e}")
            return False
    
    def remove_worktree(self, worktree_path):
        """
        Remove a worktree

        Args:
            worktree_path: worktree path

        Returns:
            bool: whether successful
        """
        try:
            if os.path.exists(worktree_path):
                self.repo.git.worktree('remove', worktree_path, '--force')
                logger.debug(f"Removed worktree: {worktree_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove worktree [{worktree_path}]: {e}")
            return False
    
    def _is_test_file(self, file_path):
        """Check whether the file is a test file"""
        return any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS)

    def _is_source_file(self, file_path):
        """Check whether the file is a source file"""
        return any(pattern in file_path for pattern in Config.SOURCE_PATH_PATTERNS)
    
    def get_full_diff(self, commit):
        """
        Get the complete diff for a commit

        Args:
            commit: commit object

        Returns:
            str: complete diff text (unified diff format)
        """
        try:
            if not commit.parents:
                return ""

            parent = commit.parents[0]

            # Get the complete unified diff
            diff_text = self.repo.git.diff(
                parent.hexsha,
                commit.hexsha,
                unified=3
            )

            return diff_text

        except Exception as e:
            logger.error(f"Failed to get complete diff [{commit.hexsha}]: {e}")
            return ""

