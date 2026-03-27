"""
Commit analyzer - responsible for analyzing the complete information of a single commit
"""

import os
import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from config import Config, AnalysisConfig
from utils.logger import get_logger
from modules import GitAnalyzer, CodeAnalyzer, ChangeDetector
from modules.diff_filter import DiffFilter
from modules.isolated_executor import IsolatedExecutor
from modules.commit_classifier import CommitClassifier

logger = get_logger()


@dataclass
class CommitAnalysisResult:
    """Complete analysis result for a single commit"""

    basic_info: Dict[str, Any] = field(default_factory=dict)
    file_changes: Dict[str, Any] = field(default_factory=dict)
    method_changes: Dict[str, Any] = field(default_factory=dict)
    diff_info: Dict[str, Any] = field(default_factory=dict)
    v1_execution: Dict[str, Any] = field(default_factory=dict)
    v05_execution: Dict[str, Any] = field(default_factory=dict)
    t05_execution: Dict[str, Any] = field(default_factory=dict)
    v0_execution: Dict[str, Any] = field(default_factory=dict)
    classification: Dict[str, Any] = field(default_factory=dict)
    test_source_mapping: Dict[str, Any] = field(default_factory=dict)
    analysis_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class CommitAnalyzer:
    """Single commit analyzer"""

    def __init__(self, repo_path: str, output_dir: str):
        """
        Initialize

        Args:
            repo_path: repository path
            output_dir: output directory
        """
        self.repo_path = repo_path
        self.output_dir = output_dir
        self.project_name = os.path.basename(repo_path)

        # Initialize components
        self.git_analyzer = GitAnalyzer(repo_path)
        self.code_analyzer = CodeAnalyzer()
        self.change_detector = ChangeDetector()
        self.diff_filter = DiffFilter()

    def analyze_full(self, commit_hash: str) -> CommitAnalysisResult:
        """
        Fully analyze a single commit

        Args:
            commit_hash: commit hash

        Returns:
            complete analysis result
        """
        start_time = datetime.now()
        result = CommitAnalysisResult()

        try:
            # 1. Collect basic information
            result.basic_info = self._collect_basic_info(commit_hash)

            # 2. Analyze file changes
            result.file_changes = self._analyze_file_changes(commit_hash)

            # 3. Analyze method changes
            result.method_changes = self._analyze_method_changes(commit_hash, result.file_changes)

            # 4. Process diff
            result.diff_info = self._process_diff(commit_hash)

            # 4.1 Calculate method-level change line counts
            result.method_changes['method_change_stats'] = self._compute_method_change_stats(
                commit_hash,
                result.basic_info.get('parent_hash'),
                result.file_changes
            )

            # 5. Execute 4 versions
            execution_results = self._execute_all_versions(
                commit_hash,
                result.basic_info.get('parent_hash'),
                result.diff_info,
                result.method_changes.get('source_methods', []),
                result.method_changes.get('test_methods', [])
            )
            result.v1_execution = execution_results.get('v1', {})
            result.v05_execution = execution_results.get('v05', {})
            result.t05_execution = execution_results.get('t05', {})
            result.v0_execution = execution_results.get('v0', {})

            # 6. Classification
            result.classification = self._classify(
                result.v1_execution,
                result.v05_execution,
                result.t05_execution,
                result.v0_execution
            )

            # 7. Analysis metadata
            end_time = datetime.now()
            result.analysis_metadata = {
                'analysis_timestamp': end_time.isoformat(),
                'analysis_duration_seconds': (end_time - start_time).total_seconds(),
                'project': self.project_name,
                'commit_hash': commit_hash,
                'phases_completed': ['basic', 'file', 'method', 'diff', 'execution', 'classification']
            }

        except Exception as e:
            logger.error(f"Failed to analyze commit {commit_hash[:8]}: {e}")
            result.analysis_metadata['error'] = str(e)

        return result

    def analyze_methods(self, commit_hash: str) -> Optional[dict]:
        """
        Perform method-level analysis only (used in Phase 2)

        Args:
            commit_hash: commit hash

        Returns:
            method analysis result, or None if no method changes exist
        """
        try:
            # Basic information
            basic_info = self._collect_basic_info(commit_hash)
            if not basic_info.get('parent_hash'):
                return None

            # File changes
            file_changes = self._analyze_file_changes(commit_hash)

            # Method changes
            method_changes = self._analyze_method_changes(commit_hash, file_changes)

            # Check if there are method-level changes
            source_methods = method_changes.get('source_methods', [])
            test_methods = method_changes.get('test_methods', [])

            if not source_methods or not test_methods:
                return None

            # Diff information
            diff_info = self._process_diff(commit_hash)
            method_change_stats = self._compute_method_change_stats(
                commit_hash,
                basic_info.get('parent_hash'),
                file_changes
            )

            return {
                'commit_hash': commit_hash,
                'parent_hash': basic_info.get('parent_hash'),
                'basic_info': basic_info,
                'file_changes': file_changes,
                'method_changes': method_changes,
                'diff_info': diff_info,
                'method_change_stats': method_change_stats,
                'has_method_changes': True
            }

        except Exception as e:
            logger.debug(f"Method analysis failed {commit_hash[:8]}: {e}")
            return None

    def analyze_execution(self, method_info: dict) -> Optional[dict]:
        """
        Execution analysis (used in Phase 3)

        Args:
            method_info: method analysis result from Phase 2

        Returns:
            complete information including execution results
        """
        commit_hash = method_info['commit_hash']
        parent_hash = method_info['parent_hash']
        diff_info = method_info['diff_info']

        try:
            # Execute 4 versions
            execution_results = self._execute_all_versions(
                commit_hash,
                parent_hash,
                diff_info,
                method_info.get('method_changes', {}).get('source_methods', []),
                method_info.get('method_changes', {}).get('test_methods', [])
            )

            # Check if both V-1 and V0 succeeded
            def _test_pass(execution: dict) -> bool:
                test_info = execution.get('test', {})
                status = test_info.get('status')
                if status:
                    return status == 'pass'
                return test_info.get('success', False)

            v1_ok = execution_results.get('v1', {}).get('build', {}).get('success', False) and \
                    _test_pass(execution_results.get('v1', {}))
            v0_ok = execution_results.get('v0', {}).get('build', {}).get('success', False) and \
                    _test_pass(execution_results.get('v0', {}))

            qualified = v1_ok and v0_ok

            # Classification
            classification = {}
            if qualified:
                classification = self._classify(
                    execution_results.get('v1', {}),
                    execution_results.get('v05', {}),
                    execution_results.get('t05', {}),
                    execution_results.get('v0', {})
                )

            # Merge results
            result = {
                **method_info,
                'v1_execution': execution_results.get('v1', {}),
                'v05_execution': execution_results.get('v05', {}),
                't05_execution': execution_results.get('t05', {}),
                'v0_execution': execution_results.get('v0', {}),
                'classification': classification,
                'qualified': qualified,
                'analysis_timestamp': datetime.now().isoformat()
            }

            return result

        except Exception as e:
            logger.error(f"Execution analysis failed {commit_hash[:8]}: {e}")
            return None

    def _collect_basic_info(self, commit_hash: str) -> dict:
        """Collect basic information"""
        commit = self.git_analyzer.repo.commit(commit_hash)
        info = self.git_analyzer.get_commit_info(commit)

        return {
            'project': self.project_name,
            'commit_hash': commit_hash,
            'short_hash': commit_hash[:8],
            'parent_hash': info.get('parent_hash'),
            'parent_short_hash': info.get('parent_hash', '')[:8] if info.get('parent_hash') else None,
            'author': info.get('author'),
            'date': info.get('date'),
            'message': info.get('message'),
            'message_subject': info.get('message', '').split('\n')[0] if info.get('message') else ''
        }

    def _analyze_file_changes(self, commit_hash: str) -> dict:
        """Analyze file changes"""
        commit = self.git_analyzer.repo.commit(commit_hash)
        changed_files = self.git_analyzer.get_changed_files(commit)

        source_files = []
        test_files = []
        other_files = []

        # Get detailed file change information
        if commit.parents:
            parent = commit.parents[0]
            diffs = parent.diff(commit)

            for diff in diffs:
                file_path = diff.b_path or diff.a_path

                # Determine change type
                if diff.new_file:
                    change_type = 'added'
                elif diff.deleted_file:
                    change_type = 'deleted'
                elif diff.renamed:
                    change_type = 'renamed'
                else:
                    change_type = 'modified'

                file_info = {
                    'path': file_path,
                    'change_type': change_type,
                    'old_path': diff.a_path if diff.renamed else None,
                    'is_java': file_path.endswith('.java')
                }

                # Classify
                if file_path in changed_files.get('source_files', []):
                    source_files.append(file_info)
                elif file_path in changed_files.get('test_files', []):
                    test_files.append(file_info)
                else:
                    other_files.append(file_info)

        return {
            'source_files': source_files,
            'test_files': test_files,
            'other_files': other_files,
            'summary': {
                'total_files': len(source_files) + len(test_files) + len(other_files),
                'source_count': len(source_files),
                'test_count': len(test_files),
                'other_count': len(other_files)
            }
        }

    def _analyze_method_changes(self, commit_hash: str, file_changes: dict) -> dict:
        """Analyze method changes

        Correctly handles method attribution for added and removed lines:
        - Added lines (+) correspond to line numbers in the current version; look up in current version's method structure
        - Removed lines (-) correspond to line numbers in the parent version; look up in parent version's method structure
        """
        commit = self.git_analyzer.repo.commit(commit_hash)
        parent_hash = commit.parents[0].hexsha if commit.parents else None

        source_methods = []
        test_methods = []

        # Analyze method changes in source files
        for file_info in file_changes.get('source_files', []):
            methods = self._analyze_single_file_methods(
                commit_hash, parent_hash, commit, file_info, is_test=False
            )
            source_methods.extend(methods)

        # Analyze method changes in test files
        for file_info in file_changes.get('test_files', []):
            methods = self._analyze_single_file_methods(
                commit_hash, parent_hash, commit, file_info, is_test=True
            )
            test_methods.extend(methods)

        return {
            'source_methods': source_methods,
            'test_methods': test_methods,
            'summary': {
                'source_methods_count': len(source_methods),
                'test_methods_count': len(test_methods)
            }
        }

    def _analyze_single_file_methods(self, commit_hash: str, parent_hash: str,
                                      commit, file_info: dict, is_test: bool) -> list:
        """Analyze method changes in a single file

        Args:
            commit_hash: current commit hash
            parent_hash: parent commit hash
            commit: commit object
            file_info: file information
            is_test: whether this is a test file

        Returns:
            list: list of changed methods
        """
        file_path = file_info.get('path')
        change_type = file_info.get('change_type')

        if not file_path or not file_path.endswith('.java'):
            return []

        try:
            diff_text = self.git_analyzer.get_file_diff(commit, file_path)
            if not diff_text:
                return []

            # Get current and parent version file content
            current_content = self.git_analyzer.get_file_content(commit_hash, file_path)
            parent_content = self.git_analyzer.get_file_content(parent_hash, file_path) if parent_hash else None

            # File was deleted: only parent version has content
            if change_type == 'deleted':
                current_content = None
            # File was added: only current version has content
            elif change_type == 'added':
                parent_content = None

            # Extract method structure for both versions
            current_methods = self._extract_methods_from_content(current_content, file_path)
            parent_methods = self._extract_methods_from_content(parent_content, file_path)

            # Parse diff to get changed line numbers
            parsed_diff = self.change_detector.parse_diff(diff_text)

            # Collect changed methods (use set for deduplication)
            changed_method_keys = set()
            changed_methods_map = {}

            for entry in parsed_diff:
                for change in entry.get('changes', []):
                    # Added lines -> look up in current version's methods
                    for line_no in change.get('added_lines', []):
                        method = self._find_method_at_line(current_methods, line_no)
                        if method:
                            key = self._get_method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                changed_methods_map[key] = method.copy()

                    # Removed lines -> look up in parent version's methods
                    for line_no in change.get('removed_lines', []):
                        method = self._find_method_at_line(parent_methods, line_no)
                        if method:
                            key = self._get_method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                # For removed lines, prefer current version's method info (if it exists)
                                current_method = self._find_method_by_key(current_methods, key)
                                changed_methods_map[key] = (current_method or method).copy()

            # Convert to result list
            result_methods = []
            for method in changed_methods_map.values():
                if is_test:
                    method['is_test_method'] = self._is_test_method(method)
                result_methods.append(method)

            return result_methods

        except Exception as e:
            logger.debug(f"Failed to analyze file methods {file_path}: {e}")
            return []

    def _extract_methods_from_content(self, content: str, file_path: str) -> list:
        """Extract all method information from file content

        Args:
            content: file content
            file_path: file path

        Returns:
            list: list of method information
        """
        if not content:
            return []

        methods = []
        classes_info = self.code_analyzer.parse_java_file(content)
        package = self.code_analyzer.get_package_name(content)

        for cls in classes_info.get('classes', []):
            for m in cls.get('methods', []):
                methods.append({
                    'class': cls.get('name'),
                    'method': m.get('name'),
                    'parameters': m.get('parameters', []),
                    'start_line': m.get('start_line', 0),
                    'end_line': m.get('end_line', 0),
                    'package': package,
                    'file': file_path,
                    'return_type': m.get('return_type'),
                    'modifiers': m.get('modifiers', [])
                })
        return methods

    def _find_method_at_line(self, methods: list, line_no: int) -> Optional[dict]:
        """Find the method at the given line number

        Args:
            methods: list of methods
            line_no: line number

        Returns:
            dict or None: found method information
        """
        for m in methods:
            if m.get('start_line', 0) <= line_no <= m.get('end_line', 0):
                return m
        return None

    def _get_method_key(self, method: dict) -> tuple:
        """Generate a unique key for a method

        Args:
            method: method information

        Returns:
            tuple: unique identifier for the method
        """
        return (
            method.get('package', ''),
            method.get('class', ''),
            method.get('method', ''),
            tuple(method.get('parameters', []))
        )

    def _find_method_by_key(self, methods: list, key: tuple) -> Optional[dict]:
        """Find a method in the list by its key

        Args:
            methods: list of methods
            key: unique identifier of the method

        Returns:
            dict or None: found method information
        """
        for m in methods:
            if self._get_method_key(m) == key:
                return m
        return None

    def _is_test_method(self, method: dict) -> bool:
        """Determine whether this is a test method"""
        method_name = method.get('method', '') or method.get('method_name', '')

        # Check if name starts with 'test'
        if method_name.lower().startswith('test'):
            return True

        # Check annotations (if present)
        annotations = method.get('annotations', [])
        test_annotations = ['@Test', '@Before', '@After', '@BeforeEach', '@AfterEach']
        for ann in test_annotations:
            if ann in annotations:
                return True

        return False

    def _process_diff(self, commit_hash: str) -> dict:
        """Process diff, separating source code and test code diffs"""
        commit = self.git_analyzer.repo.commit(commit_hash)

        # Get full diff
        full_diff = self.git_analyzer.get_full_diff(commit)

        # Separate diff
        source_diff, test_diff, stats = self.diff_filter.filter_test_changes(full_diff)
        full_stats = self.diff_filter.extract_changes_info(full_diff, label="full")
        source_stats = self.diff_filter.extract_changes_info(source_diff, label="source")
        test_stats = self.diff_filter.extract_test_changes_info(test_diff)

        return {
            'full_diff': full_diff,
            'source_only_diff': source_diff,
            'test_only_diff': test_diff,
            'stats': stats,
            'change_stats': {
                'full': full_stats,
                'source': source_stats,
                'test': test_stats
            }
        }

    def _execute_all_versions(self,
                              commit_hash: str,
                              parent_hash: str,
                              diff_info: dict,
                              changed_source_methods: Optional[list] = None,
                              changed_test_methods: Optional[list] = None) -> dict:
        """Build and test all 4 versions"""
        if not parent_hash:
            logger.warning(f"Commit {commit_hash[:8]} has no parent commit")
            return {}

        executor = IsolatedExecutor(
            repo_path=self.repo_path,
            work_dir=AnalysisConfig.ANALYSIS_WORKTREE_DIR
        )

        results = {}

        try:
            # Decide whether to execute in parallel based on configuration
            if AnalysisConfig.PARALLEL_VERSION_EXECUTION:
                results = self._execute_versions_parallel(
                    executor,
                    commit_hash,
                    parent_hash,
                    diff_info,
                    changed_source_methods,
                    changed_test_methods
                )
            else:
                results = self._execute_versions_sequential(
                    executor,
                    commit_hash,
                    parent_hash,
                    diff_info,
                    changed_source_methods,
                    changed_test_methods
                )
        finally:
            # Ensure cleanup
            executor.cleanup_all()

        return results

    def _execute_versions_sequential(self, executor: 'IsolatedExecutor',
                                     commit_hash: str, parent_hash: str,
                                     diff_info: dict,
                                     changed_source_methods: Optional[list] = None,
                                     changed_test_methods: Optional[list] = None) -> dict:
        """Execute 4 versions sequentially"""
        results = {}

        # V-1: parent commit
        logger.debug(f"  Executing V-1...")
        results['v1'] = executor.execute_version(
            commit_hash=parent_hash,
            version_type='v1',
            changed_source_methods=changed_source_methods,
            changed_test_methods=changed_test_methods
        )

        # V-0.5: parent commit + source code patch
        logger.debug(f"  Executing V-0.5...")
        results['v05'] = executor.execute_version(
            commit_hash=parent_hash,
            version_type='v05',
            patch_content=diff_info.get('source_only_diff'),
            changed_source_methods=changed_source_methods,
            changed_test_methods=changed_test_methods
        )

        # T-0.5: parent commit + test code patch
        logger.debug(f"  Executing T-0.5...")
        results['t05'] = executor.execute_version(
            commit_hash=parent_hash,
            version_type='t05',
            patch_content=diff_info.get('test_only_diff'),
            changed_source_methods=changed_source_methods,
            changed_test_methods=changed_test_methods
        )

        # V0: current commit
        logger.debug(f"  Executing V0...")
        results['v0'] = executor.execute_version(
            commit_hash=commit_hash,
            version_type='v0',
            changed_source_methods=changed_source_methods,
            changed_test_methods=changed_test_methods
        )

        return results

    def _execute_versions_parallel(self, executor: 'IsolatedExecutor',
                                   commit_hash: str, parent_hash: str,
                                   diff_info: dict,
                                   changed_source_methods: Optional[list] = None,
                                   changed_test_methods: Optional[list] = None) -> dict:
        """Execute 4 versions in parallel"""
        results = {}

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    executor.execute_version,
                    parent_hash, 'v1', None, changed_source_methods, changed_test_methods
                ): 'v1',
                pool.submit(
                    executor.execute_version,
                    parent_hash, 'v05', diff_info.get('source_only_diff'),
                    changed_source_methods, changed_test_methods
                ): 'v05',
                pool.submit(
                    executor.execute_version,
                    parent_hash, 't05', diff_info.get('test_only_diff'),
                    changed_source_methods, changed_test_methods
                ): 't05',
                pool.submit(
                    executor.execute_version,
                    commit_hash, 'v0', None, changed_source_methods, changed_test_methods
                ): 'v0'
            }

            for future in futures:
                version = futures[future]
                try:
                    results[version] = future.result(timeout=AnalysisConfig.COMMIT_TIMEOUT)
                except Exception as e:
                    logger.error(f"Execution of {version} failed: {e}")
                    results[version] = {'error': str(e)}

        return results

    def _classify(self, v1_result: dict, v05_result: dict,
                  t05_result: dict, v0_result: dict) -> dict:
        """Classify a commit"""
        classifier = CommitClassifier(
            coverage_threshold=AnalysisConfig.COVERAGE_DECREASE_THRESHOLD
        )

        return classifier.classify(v1_result, v05_result, t05_result, v0_result)

    def _compute_method_change_stats(self, commit_hash: str, parent_hash: str, file_changes: dict) -> dict:
        """Calculate added/removed line counts at the method level (source/test)"""
        stats = {'source': [], 'test': []}

        if not parent_hash:
            return stats

        commit = self.git_analyzer.repo.commit(commit_hash)

        def _collect_file_stats(file_info, category):
            file_path = file_info.get('path')
            if not file_path or not file_path.endswith('.java'):
                return

            diff_text = self.git_analyzer.get_file_diff(commit, file_path)
            if not diff_text:
                return

            parsed = self.change_detector.parse_diff(diff_text)
            file_changes_list = []
            for entry in parsed:
                if entry.get('file') == file_path:
                    file_changes_list.extend(entry.get('changes', []))

            if not file_changes_list:
                return

            child_content = self.git_analyzer.get_file_content(commit_hash, file_path) or ""
            parent_content = self.git_analyzer.get_file_content(parent_hash, file_path) or ""

            child_classes = self.code_analyzer.parse_java_file(child_content)
            parent_classes = self.code_analyzer.parse_java_file(parent_content)

            child_pkg = self.code_analyzer.get_package_name(child_content)
            parent_pkg = self.code_analyzer.get_package_name(parent_content)

            child_methods = []
            for cls in child_classes.get('classes', []):
                for m in cls.get('methods', []):
                    child_methods.append({
                        'class': cls.get('name'),
                        'method': m.get('name'),
                        'parameters': m.get('parameters', []),
                        'start_line': m.get('start_line', 0),
                        'end_line': m.get('end_line', 0),
                        'package': child_pkg,
                        'file': file_path
                    })

            parent_methods = []
            for cls in parent_classes.get('classes', []):
                for m in cls.get('methods', []):
                    parent_methods.append({
                        'class': cls.get('name'),
                        'method': m.get('name'),
                        'parameters': m.get('parameters', []),
                        'start_line': m.get('start_line', 0),
                        'end_line': m.get('end_line', 0),
                        'package': parent_pkg,
                        'file': file_path
                    })

            def _find_method(methods, line_no):
                for m in methods:
                    if m.get('start_line', 0) <= line_no <= m.get('end_line', 0):
                        return m
                return None

            method_stats = {}

            for change in file_changes_list:
                for line_no in change.get('added_lines', []):
                    m = _find_method(child_methods, line_no)
                    if not m:
                        continue
                    key = (m['package'], m['class'], m['method'], tuple(m.get('parameters', [])), file_path)
                    entry = method_stats.setdefault(key, {
                        'package': m['package'],
                        'class': m['class'],
                        'method': m['method'],
                        'parameters': m.get('parameters', []),
                        'file': file_path,
                        'added_lines': 0,
                        'removed_lines': 0
                    })
                    entry['added_lines'] += 1

                for line_no in change.get('removed_lines', []):
                    m = _find_method(parent_methods, line_no)
                    if not m:
                        continue
                    key = (m['package'], m['class'], m['method'], tuple(m.get('parameters', [])), file_path)
                    entry = method_stats.setdefault(key, {
                        'package': m['package'],
                        'class': m['class'],
                        'method': m['method'],
                        'parameters': m.get('parameters', []),
                        'file': file_path,
                        'added_lines': 0,
                        'removed_lines': 0
                    })
                    entry['removed_lines'] += 1

            for entry in method_stats.values():
                entry['total_changed_lines'] = entry.get('added_lines', 0) + entry.get('removed_lines', 0)
                stats[category].append(entry)

        for file_info in file_changes.get('source_files', []):
            _collect_file_stats(file_info, 'source')
        for file_info in file_changes.get('test_files', []):
            _collect_file_stats(file_info, 'test')

        return stats
