"""Module."""

import os
import re
from typing import Dict, Any, List, Optional, Set, Tuple

from git import Repo

from modules.code_analyzer import CodeAnalyzer
from modules.change_detector import ChangeDetector
from utils.logger import get_logger

logger = get_logger()


class ChangedMethodExtractor:
    """Changed method extractor - extracts and compares changed test methods in commits"""

    def __init__(self, repo_path: str):
        """
        Initialize the changed method extractor

        Args:
            repo_path: Repository path
        """
        self.repo_path = repo_path
        self.repo = Repo(repo_path)
        self.code_analyzer = CodeAnalyzer()
        self.change_detector = ChangeDetector()

    def extract_and_compare(self,
                            user_commit: str,
                            gt_commit: str,
                            base_commit: str) -> Dict[str, Any]:
        """
        Extract and compare changed test methods between two commits

        Args:
            user_commit: Commit hash of the user's modifications
            gt_commit: GT commit hash (V0)
            base_commit: Common base commit (parent of V-0.5)

        Returns:
            dict: {
                'common_methods': [...],      # Test methods modified in both commits
                'user_only_methods': [...],   # Methods modified only by the user
                'gt_only_methods': [...],     # Methods modified only by GT
                'user_methods': [...],        # All methods modified by the user
                'gt_methods': [...],          # All methods modified by GT
                'source_methods': [...]       # Source code methods changed in GT (for coverage analysis)
            }
        """
        result = {
            'common_methods': [],
            'user_only_methods': [],
            'gt_only_methods': [],
            'user_methods': [],
            'gt_methods': [],
            'source_methods': []
        }

        try:
            # Extract changed methods from user commit
            user_methods = self._extract_changed_test_methods(user_commit, base_commit)
            result['user_methods'] = user_methods

            # Extract changed methods from GT commit
            gt_methods = self._extract_changed_test_methods(gt_commit, base_commit)
            result['gt_methods'] = gt_methods

            # Extract changed source code methods from GT commit
            source_methods = self._extract_changed_source_methods(gt_commit, base_commit)
            result['source_methods'] = source_methods

            # Compute intersection and differences
            user_keys = self._methods_to_keys(user_methods)
            gt_keys = self._methods_to_keys(gt_methods)

            common_keys = user_keys & gt_keys
            user_only_keys = user_keys - gt_keys
            gt_only_keys = gt_keys - user_keys

            # Build results
            user_methods_map = {self._method_key(m): m for m in user_methods}
            gt_methods_map = {self._method_key(m): m for m in gt_methods}

            for key in common_keys:
                user_m = user_methods_map.get(key)
                gt_m = gt_methods_map.get(key)
                if user_m and gt_m:
                    result['common_methods'].append({
                        'class': key[1],
                        'method': key[2],
                        'file': key[0],
                        'package': user_m.get('package', ''),
                        'user_start_line': user_m.get('start_line'),
                        'user_end_line': user_m.get('end_line'),
                        'gt_start_line': gt_m.get('start_line'),
                        'gt_end_line': gt_m.get('end_line')
                    })

            for key in user_only_keys:
                m = user_methods_map.get(key)
                if m:
                    result['user_only_methods'].append(m)

            for key in gt_only_keys:
                m = gt_methods_map.get(key)
                if m:
                    result['gt_only_methods'].append(m)

            logger.debug(f"Changed method comparison: common={len(result['common_methods'])}, "
                        f"user_only={len(result['user_only_methods'])}, "
                        f"gt_only={len(result['gt_only_methods'])}")

        except Exception as e:
            logger.error(f"Failed to extract changed methods: {e}")

        return result

    def extract_method_code(self,
                            commit_hash: str,
                            file_path: str,
                            start_line: int,
                            end_line: int) -> Optional[str]:
        """
        Extract method code from the specified commit

        Args:
            commit_hash: Commit hash
            file_path: File path
            start_line: Start line number
            end_line: End line number

        Returns:
            str: Method code
        """
        try:
            content = self._get_file_content(commit_hash, file_path)
            if not content:
                return None

            lines = content.split('\n')
            if start_line < 1 or end_line > len(lines):
                return None

            return '\n'.join(lines[start_line - 1:end_line])

        except Exception as e:
            logger.debug(f"Failed to extract method code: {e}")
            return None

    def _extract_changed_test_methods(self,
                                       commit_hash: str,
                                       base_commit: str) -> List[Dict]:
        """Extract changed test methods from a commit"""
        methods = []

        try:
            commit = self.repo.commit(commit_hash)
            base = self.repo.commit(base_commit)

            # Get diff
            diffs = base.diff(commit)

            for diff in diffs:
                file_path = diff.b_path or diff.a_path
                if not file_path or not file_path.endswith('.java'):
                    continue

                # Only process test files
                if not self._is_test_file(file_path):
                    continue

                # Get file content
                content = self._get_file_content(commit_hash, file_path)
                if not content:
                    continue

                if diff.new_file:
                    # Newly added test file: extract all methods (tests added by GT developer specifically for this change)
                    file_methods = self._extract_all_methods(content, file_path)
                    methods.extend(file_methods)
                    continue

                # Get diff text
                diff_text = self._get_file_diff(commit_hash, base_commit, file_path)
                if not diff_text:
                    continue

                # Parse methods
                file_methods = self._extract_methods_from_diff(
                    content, diff_text, file_path, commit_hash, base_commit
                )
                methods.extend(file_methods)

            # Resolve data provider methods (@MethodSource-referenced methods) -> replace with actual parameterized test methods
            content_map: Dict[str, str] = {}
            for m in methods:
                fp = m.get('file', '')
                if fp and fp not in content_map:
                    c = self._get_file_content(commit_hash, fp)
                    if c:
                        content_map[fp] = c
            methods = self._resolve_data_providers(methods, content_map)

            # Keep only real test methods (with @Test/@ParameterizedTest etc. annotations), filter out helper/setup methods
            filtered = []
            for m in methods:
                fp = m.get('file', '')
                c = content_map.get(fp) or self._get_file_content(commit_hash, fp)
                if c and self._is_annotated_test_method(c, m):
                    filtered.append(m)
            methods = filtered

        except Exception as e:
            logger.error(f"Failed to extract test methods: {e}")

        return methods

    def _extract_changed_source_methods(self,
                                         commit_hash: str,
                                         base_commit: str) -> List[Dict]:
        """Extract changed source code methods from a commit"""
        methods = []

        try:
            commit = self.repo.commit(commit_hash)
            base = self.repo.commit(base_commit)

            diffs = base.diff(commit)

            for diff in diffs:
                file_path = diff.b_path or diff.a_path
                if not file_path or not file_path.endswith('.java'):
                    continue

                # Only process source code files
                if self._is_test_file(file_path):
                    continue

                if diff.new_file:
                    continue

                diff_text = self._get_file_diff(commit_hash, base_commit, file_path)
                if not diff_text:
                    continue

                content = self._get_file_content(commit_hash, file_path)
                if not content:
                    continue

                file_methods = self._extract_methods_from_diff(
                    content, diff_text, file_path, commit_hash, base_commit
                )
                methods.extend(file_methods)

        except Exception as e:
            logger.error(f"Failed to extract source code methods: {e}")

        return methods

    def _extract_methods_from_diff(self,
                                    content: str,
                                    diff_text: str,
                                    file_path: str,
                                    commit_hash: str,
                                    base_commit: str) -> List[Dict]:
        """Extract changed methods from diff"""
        methods = []

        try:
            # parse method structure of current version
            current_methods = self._extract_all_methods(content, file_path)

            # parse method structure of parent version
            parent_content = self._get_file_content(base_commit, file_path)
            parent_methods = self._extract_all_methods(parent_content, file_path) if parent_content else []

            # parse diff to get changed line numbers
            parsed_diff = self.change_detector.parse_diff(diff_text)

            # collect changed methods
            changed_method_keys = set()
            changed_methods_map = {}

            for entry in parsed_diff:
                for change in entry.get('changes', []):
                    # added lines -> search in methods of current version
                    for line_no in change.get('added_lines', []):
                        method = self._find_method_at_line(current_methods, line_no)
                        if method:
                            key = self._method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                changed_methods_map[key] = method.copy()

                    # deleted lines -> search in methods of parent version
                    for line_no in change.get('removed_lines', []):
                        method = self._find_method_at_line(parent_methods, line_no)
                        if method:
                            key = self._method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                # prefer method information from current version
                                current_method = self._find_method_by_key(current_methods, key)
                                changed_methods_map[key] = (current_method or method).copy()

            methods = list(changed_methods_map.values())

        except Exception as e:
            logger.debug(f"Failed to extract methods from diff: {e}")

        return methods

    def _resolve_data_providers(self, methods: List[Dict], content_map: Dict[str, str]) -> List[Dict]:

        if not methods:
            return methods

        by_file: Dict[str, List[Dict]] = {}
        for m in methods:
            by_file.setdefault(m.get('file', ''), []).append(m)

        resolved: List[Dict] = []
        seen_keys: Set[Tuple] = set()

        for file_path, file_methods in by_file.items():
            content = content_map.get(file_path)
            if not content:
                for m in file_methods:
                    key = self._method_key(m)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        resolved.append(m)
                continue

            # process
            # 1. @MethodSource("methodName")
            # 2. @MethodSource(value = {"methodName1", "methodName2"})
            method_source_targets: Set[str] = set()
            for annotation_block in re.findall(r'@MethodSource\s*\(([^)]+)\)', content):
                method_source_targets.update(
                    re.findall(r'"(?:[^"#]*#)?([^"]+)"', annotation_block)
                )

            # classify：
            data_provider_names: Set[str] = set()
            for m in file_methods:
                if m.get('method') in method_source_targets:
                    data_provider_names.add(m.get('method'))
                    logger.debug(
                        f"detectdatamethod（parametermethod）: "
                        f"{m.get('class')}.{m.get('method')} in {file_path}"
                    )
                else:
                    key = self._method_key(m)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        resolved.append(m)

            if not data_provider_names:
                continue

            all_file_methods = self._extract_all_methods(content, file_path)
            lines = content.split('\n')

            for m in all_file_methods:
                start = m.get('start_line', 1)
                look_start = max(0, start - 15)
                pre_text = '\n'.join(lines[look_start: start - 1])

                for dp_name in data_provider_names:
                    # 1. @MethodSource("name")
                    # 2. @MethodSource(value = {"name1", "name2"})
                    simple_pattern = (
                        r'@MethodSource\s*\(\s*"(?:[^"#]*#)?'
                        + re.escape(dp_name)
                        + r'"\s*\)'
                    )
                    array_pattern = (
                        r'@MethodSource\s*\([^)]*"(?:[^"#]*#)?'
                        + re.escape(dp_name)
                        + r'"'
                    )
                    if re.search(simple_pattern, pre_text) or re.search(array_pattern, pre_text, re.DOTALL):
                        key = self._method_key(m)
                        if key not in seen_keys:
                            seen_keys.add(key)
                            resolved.append(m)
                            logger.debug(
                                f"parametermethod: {m.get('class')}.{m.get('method')} "
                                f"(datamethod: {dp_name})"
                            )
                        break

        return resolved

    def _extract_all_methods(self, content: str, file_path: str) -> List[Dict]:
        
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
                    'file': file_path
                })

        return methods

    def _find_method_at_line(self, methods: List[Dict], line_no: int) -> Optional[Dict]:
        
        for m in methods:
            if m.get('start_line', 0) <= line_no <= m.get('end_line', 0):
                return m
        return None

    def _find_method_by_key(self, methods: List[Dict], key: Tuple) -> Optional[Dict]:
        
        for m in methods:
            if self._method_key(m) == key:
                return m
        return None

    def _method_key(self, method: Dict) -> Tuple:
        
        return (
            method.get('file', ''),
            method.get('class', ''),
            method.get('method', ''),
            tuple(method.get('parameters', []))
        )

    def _methods_to_keys(self, methods: List[Dict]) -> Set[Tuple]:
        
        return {self._method_key(m) for m in methods}

    def _is_annotated_test_method(self, content: str, method: Dict) -> bool:
        """Check if a method has a JUnit test annotation (@Test, @ParameterizedTest, @RepeatedTest)."""
        lines = content.split('\n')
        start_idx = method.get('start_line', 1) - 1  # convert to 0-based
        test_ann = {'test', 'parameterizedtest', 'repeatedtest'}
        # Scan backward up to 15 lines for test annotations
        for i in range(min(start_idx - 1, len(lines) - 1), max(0, start_idx - 15), -1):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith('//') or stripped.startswith('*'):
                continue
            if stripped.startswith('@'):
                # Extract only the annotation identifier (word chars after @)
                m = re.match(r'@(\w+)', stripped)
                if m and m.group(1).lower() in test_ann:
                    return True
            else:
                # Hit non-annotation, non-comment code — stop
                break
        return False

    def _is_test_file(self, file_path: str) -> bool:
        
        from config import Config
        return any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS)

    def _get_file_content(self, commit_hash: str, file_path: str) -> Optional[str]:
        
        try:
            commit = self.repo.commit(commit_hash)
            blob = commit.tree / file_path
            return blob.data_stream.read().decode('utf-8', errors='ignore')
        except:
            return None

    def _get_file_diff(self, commit_hash: str, base_commit: str, file_path: str) -> Optional[str]:
        
        try:
            return self.repo.git.diff(base_commit, commit_hash, '--', file_path)
        except:
            return None
