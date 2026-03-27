"""
Change detection module - responsible for analyzing diffs and identifying specifically changed methods
Uses regular expressions to parse diffs, consistent with diff_filter.py
"""

import re
from utils.logger import get_logger

logger = get_logger()


class ChangeDetector:
    """Code change detector"""

    def __init__(self):
        """Initialize the change detector"""
        pass

    def parse_diff(self, diff_text):
        """
        Parse diff text

        Args:
            diff_text: diff text content

        Returns:
            list: list of change information [{'file': str, 'changes': [{'type': str, 'start': int, 'end': int}]}]
        """
        try:
            if not diff_text:
                return []

            file_diffs = self._split_diff_by_file(diff_text)
            changes = []

            for file_diff, file_path in file_diffs:
                file_changes = {
                    'file': file_path,
                    'changes': []
                }

                # Parse hunks
                hunks = self._parse_hunks(file_diff)
                for hunk in hunks:
                    change_info = {
                        'type': 'modified',
                        'added_lines': hunk['added_lines'],
                        'removed_lines': hunk['removed_lines'],
                        'start_line': hunk['target_start'],
                        'end_line': hunk['target_start'] + hunk['target_length']
                    }
                    file_changes['changes'].append(change_info)

                changes.append(file_changes)

            return changes

        except Exception as e:
            logger.error(f"Failed to parse diff: {e}")
            return []
    
    def _split_diff_by_file(self, diff_text):
        """
        Split diff text by file

        Args:
            diff_text: complete diff text

        Returns:
            list: [(file_diff, file_path), ...]
        """
        file_diffs = []

        # Split diff text
        parts = re.split(r'(diff --git [^\n]+\n)', diff_text)

        current_diff = []
        current_path = None

        for part in parts:
            if not part:
                continue

            if part.startswith('diff --git'):
                # Save the diff of the previous file
                if current_diff and current_path:
                    file_diffs.append(("\n".join(current_diff), current_path))

                # Start a new file diff
                current_diff = [part.strip()]

                # Extract file path
                match = re.search(r'diff --git a/(.*?) b/', part)
                if match:
                    current_path = match.group(1)
                else:
                    current_path = None
            else:
                # Add to the current file's diff
                if part.strip():
                    current_diff.append(part)

        # Save the last file's diff
        if current_diff and current_path:
            file_diffs.append(("\n".join(current_diff), current_path))

        return file_diffs
    
    def _parse_hunks(self, file_diff):
        """
        Parse all hunks in a file diff

        Args:
            file_diff: diff text for a single file

        Returns:
            list: [{'target_start': int, 'target_length': int, 'added_lines': [], 'removed_lines': []}, ...]
        """
        hunks = []

        # Match hunk header: @@ -start,len +start,len @@
        hunk_pattern = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')

        # Split into lines
        lines = file_diff.split('\n')

        current_hunk = None
        target_line_no = 0
        source_line_no = 0

        for line in lines:
            hunk_match = hunk_pattern.match(line)
            if hunk_match:
                # Save the previous hunk
                if current_hunk:
                    hunks.append(current_hunk)

                # Parse hunk header
                source_start = int(hunk_match.group(1))
                source_len = int(hunk_match.group(2)) if hunk_match.group(2) else 1
                target_start = int(hunk_match.group(3))
                target_len = int(hunk_match.group(4)) if hunk_match.group(4) else 1

                current_hunk = {
                    'source_start': source_start,
                    'source_length': source_len,
                    'target_start': target_start,
                    'target_length': target_len,
                    'added_lines': [],
                    'removed_lines': []
                }
                target_line_no = target_start
                source_line_no = source_start

            elif current_hunk is not None:
                if line.startswith('+') and not line.startswith('+++'):
                    current_hunk['added_lines'].append(target_line_no)
                    target_line_no += 1
                elif line.startswith('-') and not line.startswith('---'):
                    current_hunk['removed_lines'].append(source_line_no)
                    source_line_no += 1
                elif line.startswith(' ') or line == '':
                    # Context line
                    target_line_no += 1
                    source_line_no += 1

        # Save the last hunk
        if current_hunk:
            hunks.append(current_hunk)

        return hunks
    
    def get_changed_line_ranges(self, diff_text):
        """
        Get the changed line number ranges in a diff (for the target file)

        Args:
            diff_text: diff text

        Returns:
            list: [(start_line, end_line), ...]
        """
        try:
            if not diff_text:
                return []

            ranges = []
            file_diffs = self._split_diff_by_file(diff_text)

            for file_diff, _ in file_diffs:
                hunks = self._parse_hunks(file_diff)
                for hunk in hunks:
                    start = hunk['target_start']
                    end = hunk['target_start'] + hunk['target_length']
                    ranges.append((start, end))

            return ranges

        except Exception as e:
            logger.error(f"Failed to get changed line ranges: {e}")
            return []
    
    def detect_changed_methods(self, file_content, diff_text, code_analyzer):
        """
        Detect changed methods

        Args:
            file_content: file content (after changes)
            diff_text: diff text
            code_analyzer: CodeAnalyzer instance

        Returns:
            list: list of changed methods
        """
        try:
            # Parse the file to get all methods
            classes_info = code_analyzer.parse_java_file(file_content)

            # Get the changed line ranges
            changed_ranges = self.get_changed_line_ranges(diff_text)

            # Find which methods were changed
            changed_methods = []

            for start, end in changed_ranges:
                methods = code_analyzer.get_methods_in_range(classes_info, start, end)
                for method in methods:
                    # Avoid adding duplicates
                    if not any(m['method'] == method['method'] and m['class'] == method['class']
                              for m in changed_methods):
                        changed_methods.append(method)

            return changed_methods

        except Exception as e:
            logger.error(f"Failed to detect changed methods: {e}")
            return []
    
    def has_significant_changes(self, diff_text):
        """
        Determine whether there are substantive changes (excluding whitespace, comments, etc.)

        Args:
            diff_text: diff text

        Returns:
            bool: whether there are substantive changes
        """
        try:
            if not diff_text:
                return False

            file_diffs = self._split_diff_by_file(diff_text)

            for file_diff, _ in file_diffs:
                lines = file_diff.split('\n')
                for line in lines:
                    # Skip diff metadata lines
                    if line.startswith('diff --git') or line.startswith('index ') or \
                       line.startswith('---') or line.startswith('+++') or \
                       line.startswith('@@'):
                        continue

                    # Check actual changed lines
                    if line.startswith('+') or line.startswith('-'):
                        content = line[1:].strip()
                        # Check whether the line is blank or a pure comment
                        if content and not content.startswith('//') and not content.startswith('/*'):
                            return True

            return False

        except Exception as e:
            logger.debug(f"Failed to check for substantive changes: {e}")
            return False
