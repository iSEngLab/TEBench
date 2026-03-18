"""
变更函数提取器 - 提取和对比两个commit中变更的测试函数
"""

import os
import re
from typing import Dict, Any, List, Optional, Set, Tuple

from git import Repo

from modules.code_analyzer import CodeAnalyzer
from modules.change_detector import ChangeDetector
from utils.logger import get_logger

logger = get_logger()


class ChangedMethodExtractor:
    """变更函数提取器 - 提取和对比commit中变更的测试方法"""

    def __init__(self, repo_path: str):
        """
        初始化变更函数提取器

        Args:
            repo_path: 仓库路径
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
        提取并对比两个commit中变更的测试方法

        Args:
            user_commit: 用户修改的commit hash
            gt_commit: GT commit hash (V0)
            base_commit: 共同的基础commit (V-0.5的parent)

        Returns:
            dict: {
                'common_methods': [...],  # 两个commit都修改的测试方法
                'user_only_methods': [...],  # 仅用户修改的方法
                'gt_only_methods': [...],  # 仅GT修改的方法
                'user_methods': [...],  # 用户修改的所有方法
                'gt_methods': [...],  # GT修改的所有方法
                'source_methods': [...]  # GT中变更的源代码方法（用于覆盖率分析）
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
            # 提取用户commit的变更方法
            user_methods = self._extract_changed_test_methods(user_commit, base_commit)
            result['user_methods'] = user_methods

            # 提取GT commit的变更方法
            gt_methods = self._extract_changed_test_methods(gt_commit, base_commit)
            result['gt_methods'] = gt_methods

            # 提取GT commit的源代码变更方法
            source_methods = self._extract_changed_source_methods(gt_commit, base_commit)
            result['source_methods'] = source_methods

            # 计算交集和差集
            user_keys = self._methods_to_keys(user_methods)
            gt_keys = self._methods_to_keys(gt_methods)

            common_keys = user_keys & gt_keys
            user_only_keys = user_keys - gt_keys
            gt_only_keys = gt_keys - user_keys

            # 构建结果
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

            logger.debug(f"变更方法对比: 共同={len(result['common_methods'])}, "
                        f"仅用户={len(result['user_only_methods'])}, "
                        f"仅GT={len(result['gt_only_methods'])}")

        except Exception as e:
            logger.error(f"提取变更方法失败: {e}")

        return result

    def extract_method_code(self,
                            commit_hash: str,
                            file_path: str,
                            start_line: int,
                            end_line: int) -> Optional[str]:
        """
        从指定commit中提取方法代码

        Args:
            commit_hash: commit hash
            file_path: 文件路径
            start_line: 起始行
            end_line: 结束行

        Returns:
            str: 方法代码
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
            logger.debug(f"提取方法代码失败: {e}")
            return None

    def _extract_changed_test_methods(self,
                                       commit_hash: str,
                                       base_commit: str) -> List[Dict]:
        """提取commit中变更的测试方法"""
        methods = []

        try:
            commit = self.repo.commit(commit_hash)
            base = self.repo.commit(base_commit)

            # 获取diff
            diffs = base.diff(commit)

            for diff in diffs:
                file_path = diff.b_path or diff.a_path
                if not file_path or not file_path.endswith('.java'):
                    continue

                # 只处理测试文件
                if not self._is_test_file(file_path):
                    continue

                # 获取文件内容
                content = self._get_file_content(commit_hash, file_path)
                if not content:
                    continue

                if diff.new_file:
                    # 新增的测试文件：提取所有方法（GT开发者专门为本次变更添加的测试）
                    file_methods = self._extract_all_methods(content, file_path)
                    methods.extend(file_methods)
                    continue

                # 获取diff文本
                diff_text = self._get_file_diff(commit_hash, base_commit, file_path)
                if not diff_text:
                    continue

                # 解析方法
                file_methods = self._extract_methods_from_diff(
                    content, diff_text, file_path, commit_hash, base_commit
                )
                methods.extend(file_methods)

            # 解析数据提供方法（@MethodSource 引用的方法）→ 替换为实际的参数化测试方法
            content_map: Dict[str, str] = {}
            for m in methods:
                fp = m.get('file', '')
                if fp and fp not in content_map:
                    c = self._get_file_content(commit_hash, fp)
                    if c:
                        content_map[fp] = c
            methods = self._resolve_data_providers(methods, content_map)

            # 只保留真正的测试方法（有@Test/@ParameterizedTest等注解），过滤掉helper/setup方法
            filtered = []
            for m in methods:
                fp = m.get('file', '')
                c = content_map.get(fp) or self._get_file_content(commit_hash, fp)
                if c and self._is_annotated_test_method(c, m):
                    filtered.append(m)
            methods = filtered

        except Exception as e:
            logger.error(f"提取测试方法失败: {e}")

        return methods

    def _extract_changed_source_methods(self,
                                         commit_hash: str,
                                         base_commit: str) -> List[Dict]:
        """提取commit中变更的源代码方法"""
        methods = []

        try:
            commit = self.repo.commit(commit_hash)
            base = self.repo.commit(base_commit)

            diffs = base.diff(commit)

            for diff in diffs:
                file_path = diff.b_path or diff.a_path
                if not file_path or not file_path.endswith('.java'):
                    continue

                # 只处理源代码文件
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
            logger.error(f"提取源代码方法失败: {e}")

        return methods

    def _extract_methods_from_diff(self,
                                    content: str,
                                    diff_text: str,
                                    file_path: str,
                                    commit_hash: str,
                                    base_commit: str) -> List[Dict]:
        """从diff中提取变更的方法"""
        methods = []

        try:
            # 解析当前版本的方法结构
            current_methods = self._extract_all_methods(content, file_path)

            # 解析父版本的方法结构
            parent_content = self._get_file_content(base_commit, file_path)
            parent_methods = self._extract_all_methods(parent_content, file_path) if parent_content else []

            # 解析diff获取变更行号
            parsed_diff = self.change_detector.parse_diff(diff_text)

            # 收集变更的方法
            changed_method_keys = set()
            changed_methods_map = {}

            for entry in parsed_diff:
                for change in entry.get('changes', []):
                    # 新增行 -> 在当前版本的方法中查找
                    for line_no in change.get('added_lines', []):
                        method = self._find_method_at_line(current_methods, line_no)
                        if method:
                            key = self._method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                changed_methods_map[key] = method.copy()

                    # 删除行 -> 在父版本的方法中查找
                    for line_no in change.get('removed_lines', []):
                        method = self._find_method_at_line(parent_methods, line_no)
                        if method:
                            key = self._method_key(method)
                            if key not in changed_method_keys:
                                changed_method_keys.add(key)
                                # 优先使用当前版本的方法信息
                                current_method = self._find_method_by_key(current_methods, key)
                                changed_methods_map[key] = (current_method or method).copy()

            methods = list(changed_methods_map.values())

        except Exception as e:
            logger.debug(f"从diff提取方法失败: {e}")

        return methods

    def _resolve_data_providers(self, methods: List[Dict], content_map: Dict[str, str]) -> List[Dict]:
        """
        检测数据提供方法（被 @MethodSource 引用的方法），将其替换为实际的参数化测试方法。

        当变更方法列表中存在被 @MethodSource("X") 引用的方法 X 时：
        - 将 X 从列表中移除（它不是真正的可执行测试）
        - 找到所有通过 @MethodSource("X") / @MethodSource("ClassName#X") 使用 X 的测试方法
        - 将这些真正的参数化测试方法加入结果列表

        Args:
            methods: 已提取的变更方法列表
            content_map: {file_path: file_content} 各测试文件内容映射

        Returns:
            list: 将数据提供方法替换为对应参数化测试方法后的列表
        """
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

            # 收集此文件中所有被 @MethodSource 引用的方法名
            # 处理两种语法:
            # 1. @MethodSource("methodName")
            # 2. @MethodSource(value = {"methodName1", "methodName2"})
            method_source_targets: Set[str] = set()
            for annotation_block in re.findall(r'@MethodSource\s*\(([^)]+)\)', content):
                method_source_targets.update(
                    re.findall(r'"(?:[^"#]*#)?([^"]+)"', annotation_block)
                )

            # 分类：普通测试方法 vs 数据提供方法
            data_provider_names: Set[str] = set()
            for m in file_methods:
                if m.get('method') in method_source_targets:
                    data_provider_names.add(m.get('method'))
                    logger.debug(
                        f"检测到数据提供方法（将替换为参数化测试方法）: "
                        f"{m.get('class')}.{m.get('method')} in {file_path}"
                    )
                else:
                    key = self._method_key(m)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        resolved.append(m)

            if not data_provider_names:
                continue

            # 对每个数据提供方法，找到引用它的参数化测试方法
            all_file_methods = self._extract_all_methods(content, file_path)
            lines = content.split('\n')

            for m in all_file_methods:
                start = m.get('start_line', 1)
                # 向上最多查找 15 行，寻找 @MethodSource 注解
                look_start = max(0, start - 15)
                pre_text = '\n'.join(lines[look_start: start - 1])

                for dp_name in data_provider_names:
                    # 支持两种 @MethodSource 语法:
                    # 1. @MethodSource("name") 或 @MethodSource("Class#name")
                    # 2. @MethodSource(value = {"name1", "name2"}) 或 @MethodSource({"name1"})
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
                                f"添加参数化测试方法: {m.get('class')}.{m.get('method')} "
                                f"(数据提供方法: {dp_name})"
                            )
                        break

        return resolved

    def _extract_all_methods(self, content: str, file_path: str) -> List[Dict]:
        """从文件内容中提取所有方法"""
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
        """根据行号找到对应的方法"""
        for m in methods:
            if m.get('start_line', 0) <= line_no <= m.get('end_line', 0):
                return m
        return None

    def _find_method_by_key(self, methods: List[Dict], key: Tuple) -> Optional[Dict]:
        """根据方法key查找方法"""
        for m in methods:
            if self._method_key(m) == key:
                return m
        return None

    def _method_key(self, method: Dict) -> Tuple:
        """生成方法的唯一标识key（包含参数类型，以区分同名重载方法）"""
        return (
            method.get('file', ''),
            method.get('class', ''),
            method.get('method', ''),
            tuple(method.get('parameters', []))
        )

    def _methods_to_keys(self, methods: List[Dict]) -> Set[Tuple]:
        """将方法列表转换为key集合"""
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
        """判断是否为测试文件"""
        from config import Config
        return any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS)

    def _get_file_content(self, commit_hash: str, file_path: str) -> Optional[str]:
        """获取指定commit中的文件内容"""
        try:
            commit = self.repo.commit(commit_hash)
            blob = commit.tree / file_path
            return blob.data_stream.read().decode('utf-8', errors='ignore')
        except:
            return None

    def _get_file_diff(self, commit_hash: str, base_commit: str, file_path: str) -> Optional[str]:
        """获取文件的diff"""
        try:
            return self.repo.git.diff(base_commit, commit_hash, '--', file_path)
        except:
            return None
