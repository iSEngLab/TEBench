#!/usr/bin/env python3
"""
Ground Truth测试变更提取器
从GT commit中提取测试用例的变更information（新增/修改/delete）
"""

import re
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from git import Repo


@dataclass
class TestMethodChange:
    """测试method变更information"""
    method_name: str
    change_type: str  # 'added', 'modified', 'deleted'
    file_path: str
    lines_added: int = 0
    lines_deleted: int = 0


@dataclass
class TestFileChange:
    """test files变更information"""
    file_path: str
    change_type: str  # 'modified', 'added', 'deleted'
    added_methods: List[str]
    modified_methods: List[str]
    deleted_methods: List[str]
    lines_added: int
    lines_deleted: int


@dataclass
class TaskTestChanges:
    """单个task的测试变更information"""
    task_id: int
    project: str
    v_minus_1_commit: str
    v_0_commit: str
    task_type: str
    modified_files: List[Dict]
    added_files: List[Dict]
    deleted_files: List[Dict]
    summary: Dict


class GTTestChangeExtractor:
    """Ground Truth测试变更提取器"""

    # 测试method的正则表达式模式
    TEST_METHOD_PATTERN = re.compile(
        r'^\s*(?:@Test\s+)?(?:public|private|protected)?\s+(?:static\s+)?void\s+(\w+)\s*\(',
        re.MULTILINE
    )

    # @Test注解模式
    TEST_ANNOTATION_PATTERN = re.compile(r'^\s*@Test', re.MULTILINE)

    def __init__(self, project_path: str):
        """
        initialize提取器

        Args:
            project_path: projectpath
        """
        self.project_path = project_path
        self.repo = Repo(project_path)

    def extract_test_changes(self, v_minus_1: str, v_0: str) -> Dict:
        """
        提取两个version之间的测试变更

        Args:
            v_minus_1: 旧versioncommit hash
            v_0: GTversioncommit hash

        Returns:
            测试变更information字典
        """
        # get所有变更的test files
        changed_files = self._get_changed_test_files(v_minus_1, v_0)

        modified_files = []
        added_files = []
        deleted_files = []

        for file_path, change_type in changed_files.items():
            if change_type == 'A':
                # 新增file
                file_info = self._analyze_added_file(file_path, v_0)
                added_files.append(file_info)
            elif change_type == 'D':
                # deletefile
                file_info = self._analyze_deleted_file(file_path, v_minus_1)
                deleted_files.append(file_info)
            elif change_type == 'M':
                # 修改file
                file_info = self._analyze_modified_file(file_path, v_minus_1, v_0)
                if file_info:
                    modified_files.append(file_info)

        # generate摘要
        summary = self._generate_summary(modified_files, added_files, deleted_files)

        return {
            'modified_files': modified_files,
            'added_files': added_files,
            'deleted_files': deleted_files,
            'summary': summary
        }

    def _get_changed_test_files(self, v_minus_1: str, v_0: str) -> Dict[str, str]:
        """
        get变更的test files列表

        Returns:
            {file_path: change_type} 字典，change_type为 'A'(added), 'M'(modified), 'D'(deleted)
        """
        # 使用git diffgetfile变更
        diff_output = self.repo.git.diff(
            v_minus_1, v_0,
            '--name-status',
            '--diff-filter=AMD'
        )

        changed_files = {}
        for line in diff_output.split('\n'):
            if not line.strip():
                continue

            parts = line.split('\t')
            if len(parts) < 2:
                continue

            change_type = parts[0]
            file_path = parts[1]

            # 只关注test files
            if 'test' in file_path.lower() and file_path.endswith('.java'):
                changed_files[file_path] = change_type

        return changed_files

    def _get_file_content(self, file_path: str, commit: str) -> Optional[str]:
        """get指定commit的file内容"""
        try:
            return self.repo.git.show(f'{commit}:{file_path}')
        except Exception:
            return None

    def _extract_test_methods(self, content: str) -> Set[str]:
        """
        从file内容中提取测试method名

        Args:
            content: file内容

        Returns:
            测试method名集合
        """
        if not content:
            return set()

        methods = set()
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # check是否有@Test注解
            if self.TEST_ANNOTATION_PATTERN.search(line):
                # 查找下一行的method定义
                for j in range(i + 1, min(i + 5, len(lines))):
                    match = self.TEST_METHOD_PATTERN.search(lines[j])
                    if match:
                        methods.add(match.group(1))
                        break
            else:
                # 直接匹配method定义（可能@Testin同一行或method名包含test）
                match = self.TEST_METHOD_PATTERN.search(line)
                if match:
                    method_name = match.group(1)
                    # checkmethod名是否包含test或前面有@Test
                    if 'test' in method_name.lower() or (i > 0 and '@Test' in lines[i-1]):
                        methods.add(method_name)

        return methods

    def _get_file_diff_stats(self, file_path: str, v_minus_1: str, v_0: str) -> Tuple[int, int]:
        """
        getfile的增删行数statistics

        Returns:
            (lines_added, lines_deleted)
        """
        try:
            diff_output = self.repo.git.diff(
                v_minus_1, v_0,
                '--numstat',
                '--', file_path
            )

            if diff_output.strip():
                parts = diff_output.split('\t')
                if len(parts) >= 2:
                    added = int(parts[0]) if parts[0] != '-' else 0
                    deleted = int(parts[1]) if parts[1] != '-' else 0
                    return added, deleted
        except Exception:
            pass

        return 0, 0

    def _analyze_added_file(self, file_path: str, v_0: str) -> Dict:
        """分析新增的test files"""
        content = self._get_file_content(file_path, v_0)
        methods = self._extract_test_methods(content)

        lines_added = len(content.split('\n')) if content else 0

        return {
            'file_path': file_path,
            'change_type': 'added',
            'added_methods': sorted(list(methods)),
            'modified_methods': [],
            'deleted_methods': [],
            'lines_added': lines_added,
            'lines_deleted': 0
        }

    def _analyze_deleted_file(self, file_path: str, v_minus_1: str) -> Dict:
        """分析delete的test files"""
        content = self._get_file_content(file_path, v_minus_1)
        methods = self._extract_test_methods(content)

        lines_deleted = len(content.split('\n')) if content else 0

        return {
            'file_path': file_path,
            'change_type': 'deleted',
            'added_methods': [],
            'modified_methods': [],
            'deleted_methods': sorted(list(methods)),
            'lines_added': 0,
            'lines_deleted': lines_deleted
        }

    def _get_file_content_from_workdir(self, file_path: str) -> Optional[str]:
        """
        从working directory读取file内容

        Args:
            file_path: file path（相对于仓库根directory）

        Returns:
            file内容，如果file不存inreturnNone
        """
        import os
        full_path = os.path.join(self.project_path, file_path)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return None

    def _analyze_added_file_from_workdir(self, file_path: str) -> Dict:
        """分析从working directory新增的test files"""
        content = self._get_file_content_from_workdir(file_path)
        methods = self._extract_test_methods(content)

        lines_added = len(content.split('\n')) if content else 0

        return {
            'file_path': file_path,
            'change_type': 'added',
            'added_methods': sorted(list(methods)),
            'modified_methods': [],
            'deleted_methods': [],
            'lines_added': lines_added,
            'lines_deleted': 0
        }

    def _analyze_modified_file_with_workdir(self, file_path: str, v_minus_1: str) -> Optional[Dict]:
        """分析修改的test files（与working directory比较）"""
        old_content = self._get_file_content(file_path, v_minus_1)
        new_content = self._get_file_content_from_workdir(file_path)

        if old_content is None or new_content is None:
            return None

        old_methods = self._extract_test_methods(old_content)
        new_methods = self._extract_test_methods(new_content)

        added_methods = new_methods - old_methods
        deleted_methods = old_methods - new_methods
        common_methods = old_methods & new_methods

        # detect修改的method
        modified_methods = self._detect_modified_methods(
            file_path, v_minus_1, None, common_methods
        )

        # getdiffstatistics（需要特殊processworking directory）
        lines_added, lines_deleted = self._get_file_diff_stats_with_workdir(file_path, v_minus_1)

        return {
            'file_path': file_path,
            'change_type': 'modified',
            'added_methods': sorted(list(added_methods)),
            'modified_methods': sorted(list(modified_methods)),
            'deleted_methods': sorted(list(deleted_methods)),
            'lines_added': lines_added,
            'lines_deleted': lines_deleted
        }

    def _get_file_diff_stats_with_workdir(self, file_path: str, v_minus_1: str) -> Tuple[int, int]:
        """
        getfile与working directory的增删行数statistics

        Returns:
            (lines_added, lines_deleted)
        """
        try:
            diff_output = self.repo.git.diff(
                v_minus_1,
                '--numstat',
                '--', file_path
            )

            if diff_output.strip():
                parts = diff_output.split('\t')
                if len(parts) >= 2:
                    added = int(parts[0]) if parts[0] != '-' else 0
                    deleted = int(parts[1]) if parts[1] != '-' else 0
                    return added, deleted
        except Exception:
            pass

        return 0, 0

    def _analyze_modified_file(self, file_path: str, v_minus_1: str, v_0: str) -> Optional[Dict]:
        """分析修改的test files"""
        old_content = self._get_file_content(file_path, v_minus_1)
        new_content = self._get_file_content(file_path, v_0)

        if old_content is None or new_content is None:
            return None

        old_methods = self._extract_test_methods(old_content)
        new_methods = self._extract_test_methods(new_content)

        # calculate变更
        added_methods = new_methods - old_methods
        deleted_methods = old_methods - new_methods
        common_methods = old_methods & new_methods

        # check共同method是否被修改
        modified_methods = self._detect_modified_methods(
            file_path, v_minus_1, v_0, common_methods
        )

        # get增删行数
        lines_added, lines_deleted = self._get_file_diff_stats(file_path, v_minus_1, v_0)

        return {
            'file_path': file_path,
            'change_type': 'modified',
            'added_methods': sorted(list(added_methods)),
            'modified_methods': sorted(list(modified_methods)),
            'deleted_methods': sorted(list(deleted_methods)),
            'lines_added': lines_added,
            'lines_deleted': lines_deleted
        }

    def _detect_modified_methods(self, file_path: str, v_minus_1: str, v_0: Optional[str],
                                  methods: Set[str]) -> Set[str]:
        """
        detect哪些method被修改了

        通过提取每个method的内容并比较来判断

        Args:
            file_path: file path
            v_minus_1: 旧versioncommit hash
            v_0: 新versioncommit hash，如果为None则使用working directory
            methods: 要check的method集合
        """
        if not methods:
            return set()

        try:
            old_content = self._get_file_content(file_path, v_minus_1)

            # 如果v_0为None，从working directory读取
            if v_0 is None:
                new_content = self._get_file_content_from_workdir(file_path)
            else:
                new_content = self._get_file_content(file_path, v_0)

            if not old_content or not new_content:
                return set()

            modified = set()

            for method in methods:
                # 提取method体
                old_method_body = self._extract_method_body(old_content, method)
                new_method_body = self._extract_method_body(new_content, method)

                # 比较method体是否有变化
                if old_method_body and new_method_body and old_method_body != new_method_body:
                    modified.add(method)

            return modified

        except Exception:
            return set()

    def _extract_method_body(self, content: str, method_name: str) -> Optional[str]:
        """
        提取指定method的method体

        Args:
            content: file内容
            method_name: method名

        Returns:
            method体内容（从method定义到method结束的大括号）
        """
        if not content:
            return None

        lines = content.split('\n')
        method_pattern = rf'^\s*(?:@Test\s+)?(?:public|private|protected)?\s+(?:static\s+)?void\s+{re.escape(method_name)}\s*\('

        # 查找method定义
        method_start = -1
        for i, line in enumerate(lines):
            if re.search(method_pattern, line):
                method_start = i
                break

        if method_start == -1:
            return None

        # 查找method体的start（第一个{）
        brace_start = -1
        for i in range(method_start, len(lines)):
            if '{' in lines[i]:
                brace_start = i
                break

        if brace_start == -1:
            return None

        # 使用括号匹配foundmethod结束
        brace_count = 0
        method_end = -1

        for i in range(brace_start, len(lines)):
            line = lines[i]
            # 简单的括号计数（忽略字符串和注释中的括号）
            for char in line:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        method_end = i
                        break
            if method_end != -1:
                break

        if method_end == -1:
            return None

        # returnmethod体内容
        return '\n'.join(lines[method_start:method_end + 1])

    def _generate_summary(self, modified_files: List[Dict],
                         added_files: List[Dict],
                         deleted_files: List[Dict]) -> Dict:
        """generate变更摘要"""
        total_methods_added = sum(len(f['added_methods']) for f in modified_files + added_files)
        total_methods_modified = sum(len(f['modified_methods']) for f in modified_files)
        total_methods_deleted = sum(len(f['deleted_methods']) for f in modified_files + deleted_files)

        return {
            'total_test_methods_added': total_methods_added,
            'total_test_methods_modified': total_methods_modified,
            'total_test_methods_deleted': total_methods_deleted,
            'total_test_files_modified': len(modified_files),
            'total_test_files_added': len(added_files),
            'total_test_files_deleted': len(deleted_files)
        }
