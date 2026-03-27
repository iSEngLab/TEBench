"""
Diff filter - responsible for filtering test code changes out of the complete diff
"""

import re
from config import Config
from utils.logger import get_logger

logger = get_logger()


class DiffFilter:
    """Diff filter - separates source code changes from test code changes"""

    def __init__(self):
        """Initialize the diff filter"""
        pass

    def filter_test_changes(self, diff_text):
        """
        Filter test file changes out of the complete diff, keeping only source code changes

        Args:
            diff_text: complete diff text

        Returns:
            tuple: (filtered_diff: str, test_diff: str, stats: dict)
                - filtered_diff: diff containing only source code changes
                - test_diff: diff containing only test code changes
                - stats: statistics
        """
        try:
            if not diff_text:
                return "", "", {"source_files": 0, "test_files": 0}

            # Split diff by file
            file_diffs = self._split_diff_by_file(diff_text)

            source_diffs = []
            test_diffs = []

            for file_diff, file_path in file_diffs:
                # Determine file type
                if self._is_test_file(file_path):
                    test_diffs.append(file_diff)
                else:
                    source_diffs.append(file_diff)

            # Merge diff texts
            filtered_diff = "\n".join(source_diffs)
            test_diff = "\n".join(test_diffs)

            stats = {
                "source_files": len(source_diffs),
                "test_files": len(test_diffs),
                "filtered": len(test_diffs) > 0
            }

            logger.debug(f"Diff filter: {stats['source_files']} source files, {stats['test_files']} test files")

            return filtered_diff, test_diff, stats

        except Exception as e:
            logger.error(f"Failed to filter diff: {e}")
            return "", "", {"source_files": 0, "test_files": 0, "error": str(e)}

    def _is_test_file(self, file_path):
        """Check whether the file is a test file"""
        return any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS)

    def _split_diff_by_file(self, diff_text):
        """
        Split diff text by file

        Args:
            diff_text: complete diff text

        Returns:
            list: [(file_diff, file_path), ...]
        """
        file_diffs = []

        # Process line by line, only matching "diff --git" at the start of a line
        # This avoids false matches against "diff --git" strings inside diff content
        lines = diff_text.split('\n')

        current_diff_lines = []
        current_path = None

        for line in lines:
            # Check if this is the start of a new file (must be at the start of the line)
            if line.startswith('diff --git '):
                # Save the diff of the previous file
                if current_diff_lines and current_path:
                    file_diffs.append(('\n'.join(current_diff_lines), current_path))

                # Start a new file diff
                current_diff_lines = [line]

                # Extract file path
                match = re.search(r'diff --git a/(.*?) b/', line)
                if match:
                    current_path = match.group(1)
                else:
                    current_path = None
            else:
                # Add to the current file's diff
                current_diff_lines.append(line)

        # Save the last file's diff
        if current_diff_lines and current_path:
            file_diffs.append(('\n'.join(current_diff_lines), current_path))

        return file_diffs

    def extract_test_changes_info(self, test_diff):
        """
        Extract change information from the test diff

        Args:
            test_diff: diff of test code

        Returns:
            dict: test change information
        """
        return self.extract_changes_info(test_diff, label="test")

    def extract_changes_info(self, diff_text, label=""):
        """
        Extract change information from a diff (generic)

        Args:
            diff_text: diff text
            label: log label

        Returns:
            dict: change information
        """
        try:
            if not diff_text:
                return {"files": [], "total_lines_added": 0, "total_lines_removed": 0}

            file_diffs = self._split_diff_by_file(diff_text)
            files_info = []
            total_added = 0
            total_removed = 0

            for file_diff, file_path in file_diffs:
                # Count added and removed lines
                added = len([
                    line for line in file_diff.split('\n')
                    if line.startswith('+') and not line.startswith('+++')
                ])
                removed = len([
                    line for line in file_diff.split('\n')
                    if line.startswith('-') and not line.startswith('---')
                ])

                # Detect new files and deleted files
                is_new = 'new file mode' in file_diff
                is_deleted = 'deleted file mode' in file_diff

                file_info = {
                    "path": file_path,
                    "lines_added": added,
                    "lines_removed": removed,
                    "is_new": is_new,
                    "is_deleted": is_deleted
                }
                files_info.append(file_info)
                total_added += added
                total_removed += removed

            return {
                "files": files_info,
                "total_lines_added": total_added,
                "total_lines_removed": total_removed
            }

        except Exception as e:
            prefix = f"{label} change" if label else "change"
            logger.error(f"Failed to extract {prefix} information: {e}")
            return {"files": [], "total_lines_added": 0, "total_lines_removed": 0}
