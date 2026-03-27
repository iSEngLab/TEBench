"""
Commit filter - responsible for applying various filter conditions
"""

from utils.logger import get_logger

logger = get_logger()


class CommitFilter:
    """Commit filter"""

    def __init__(self):
        """Initialize the filter"""
        pass

    def filter_by_file_changes(self, changed_files):
        """
        Filter by file changes: both test files and source files must be modified

        Args:
            changed_files: changed files dictionary {'test_files': [], 'source_files': []}

        Returns:
            bool: whether the filter is passed
        """
        has_test_changes = len(changed_files.get('test_files', [])) > 0
        has_source_changes = len(changed_files.get('source_files', [])) > 0

        passed = has_test_changes and has_source_changes

        if not passed:
            reason = []
            if not has_test_changes:
                reason.append("no test file changes")
            if not has_source_changes:
                reason.append("no source file changes")
            logger.debug(f"Filtered: {', '.join(reason)}")

        return passed

    def filter_by_build_status(self, build_status):
        """
        Filter by build status: both parent commit and child commit must build successfully

        Args:
            build_status: build status dictionary {'parent_success': bool, 'child_success': bool}

        Returns:
            bool: whether the filter is passed
        """
        parent_ok = build_status.get('parent_success', False)
        child_ok = build_status.get('child_success', False)

        passed = parent_ok and child_ok

        if not passed:
            reasons = []
            if not parent_ok:
                reasons.append("parent commit build failed")
            if not child_ok:
                reasons.append("child commit build failed")
            logger.debug(f"Filtered: {', '.join(reasons)}")

        return passed

    def filter_by_coverage_threshold(self, coverage_analysis, threshold=0.5):
        """
        Filter by coverage threshold: at least threshold fraction of tests must cover changed methods under test

        Args:
            coverage_analysis: coverage analysis results
            threshold: coverage threshold (default 0.5, i.e. 50%)

        Returns:
            bool: whether the filter is passed
        """
        # Check coverage for parent commit and child commit
        parent_coverage = coverage_analysis.get('parent_commit', {})
        child_coverage = coverage_analysis.get('child_commit', {})

        parent_ratio = parent_coverage.get('coverage_ratio', 0.0)
        child_ratio = child_coverage.get('coverage_ratio', 0.0)

        # Pass if either version reaches the threshold
        passed = parent_ratio >= threshold or child_ratio >= threshold

        if not passed:
            logger.debug(f"Filtered: insufficient coverage (parent: {parent_ratio:.2%}, child: {child_ratio:.2%}, threshold: {threshold:.2%})")

        return passed

    def filter_by_method_changes(self, changed_methods):
        """
        Filter by method changes: there must be explicit test method and source method changes

        Args:
            changed_methods: changed methods dictionary {'test_methods': [], 'source_methods': []}

        Returns:
            bool: whether the filter is passed
        """
        has_test_method_changes = len(changed_methods.get('test_methods', [])) > 0
        has_source_method_changes = len(changed_methods.get('source_methods', [])) > 0

        passed = has_test_method_changes and has_source_method_changes

        if not passed:
            reasons = []
            if not has_test_method_changes:
                reasons.append("no test method changes")
            if not has_source_method_changes:
                reasons.append("no source method changes")
            logger.debug(f"Filtered: {', '.join(reasons)}")

        return passed

    def apply_all_filters(self, commit_info, threshold=0.5):
        """
        Apply all filter conditions

        Args:
            commit_info: commit information dictionary
            threshold: coverage threshold

        Returns:
            tuple: (passed: bool, reasons: list)
        """
        reasons = []

        # 1. File change filter
        if not self.filter_by_file_changes(commit_info.get('changed_files', {})):
            reasons.append("file changes do not meet requirements")

        # 2. Method change filter
        if not self.filter_by_method_changes(commit_info.get('changed_methods', {})):
            reasons.append("method changes do not meet requirements")

        # 3. Build status filter
        if not self.filter_by_build_status(commit_info.get('build_status', {})):
            reasons.append("build failed")

        # 4. Coverage filter
        if not self.filter_by_coverage_threshold(commit_info.get('coverage_analysis', {}), threshold):
            reasons.append("insufficient coverage")

        passed = len(reasons) == 0

        return passed, reasons
