"""
覆盖增量分析器 - 计算和比较覆盖增量
"""

import os
import subprocess
from typing import Dict, Any, List, Set, Optional

from config import Config, AnalysisConfig
from modules.coverage_analyzer import CoverageAnalyzer
from utils.logger import get_logger

logger = get_logger()


class CoverageIncrementAnalyzer:
    """覆盖增量分析器 - 计算覆盖增量和重合度"""

    def __init__(self):
        """初始化覆盖增量分析器"""
        self.coverage_analyzer = CoverageAnalyzer()

    def analyze(self,
                v05_worktree: str,
                user_worktree: str,
                gt_worktree: str,
                source_methods: List[Dict],
                test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        分析覆盖增量

        Args:
            v05_worktree: V-0.5版本的worktree路径
            user_worktree: 用户修改版本的worktree路径
            gt_worktree: GT (V0)版本的worktree路径
            source_methods: 变更的源代码方法列表
            test_methods: 要执行的测试方法列表（User+GT并集），None则跑全量

        Returns:
            dict: {
                'v05_coverage': {...},
                'user_coverage': {...},
                'gt_coverage': {...},
                'gt_increment': {'lines': set, 'branches': set},
                'user_increment': {'lines': set, 'branches': set},
                'overlap_ratio': {'line': float, 'branch': float},
                'gt_has_increment': bool,
                'error': str
            }
        """
        result = {
            'v05_coverage': {},
            'user_coverage': {},
            'gt_coverage': {},
            'gt_increment': {'lines': set(), 'branches': set()},
            'user_increment': {'lines': set(), 'branches': set()},
            'overlap_ratio': {'line': 0.0, 'branch': 0.0},
            'gt_has_increment': False,
            'error': None
        }

        try:
            # 1. 收集V-0.5的覆盖率
            v05_coverage = self._collect_coverage(v05_worktree, source_methods, test_methods)
            result['v05_coverage'] = v05_coverage

            # 2. 收集用户版本的覆盖率
            user_coverage = self._collect_coverage(user_worktree, source_methods, test_methods)
            result['user_coverage'] = user_coverage

            # 3. 收集GT版本的覆盖率
            gt_coverage = self._collect_coverage(gt_worktree, source_methods, test_methods)
            result['gt_coverage'] = gt_coverage

            # 4. 计算增量
            v05_lines = self._extract_covered_lines(v05_coverage, source_methods)
            user_lines = self._extract_covered_lines(user_coverage, source_methods)
            gt_lines = self._extract_covered_lines(gt_coverage, source_methods)

            logger.debug(f"V-0.5 覆盖行数: {len(v05_lines)}")
            logger.debug(f"User 覆盖行数: {len(user_lines)}")
            logger.debug(f"GT 覆盖行数: {len(gt_lines)}")

            gt_increment_lines = gt_lines - v05_lines
            user_increment_lines = user_lines - v05_lines

            logger.debug(f"GT 增量行: {gt_increment_lines}")
            logger.debug(f"User 增量行: {user_increment_lines}")

            result['gt_increment']['lines'] = gt_increment_lines
            result['user_increment']['lines'] = user_increment_lines

            # 5. 计算分支覆盖增量
            v05_branches = self._extract_covered_branches(v05_coverage, source_methods)
            user_branches = self._extract_covered_branches(user_coverage, source_methods)
            gt_branches = self._extract_covered_branches(gt_coverage, source_methods)

            gt_increment_branches = gt_branches - v05_branches
            user_increment_branches = user_branches - v05_branches

            result['gt_increment']['branches'] = gt_increment_branches
            result['user_increment']['branches'] = user_increment_branches

            # 标记GT是否有增量
            result['gt_has_increment'] = bool(gt_increment_lines or gt_increment_branches)

            # 6. 计算重合度
            result['overlap_ratio']['line'] = self._calculate_overlap(
                user_increment_lines, gt_increment_lines
            )
            result['overlap_ratio']['branch'] = self._calculate_overlap(
                user_increment_branches, gt_increment_branches
            )

            logger.debug(f"覆盖增量分析: GT增量行={len(gt_increment_lines)}, "
                        f"User增量行={len(user_increment_lines)}, "
                        f"行重合度={result['overlap_ratio']['line']:.2%}, "
                        f"GT有增量={result['gt_has_increment']}")

        except Exception as e:
            logger.error(f"覆盖增量分析失败: {e}")
            result['error'] = str(e)

        return result

    def analyze_gt_baseline(self,
                            user_worktree: str,
                            gt_worktree: str,
                            source_methods: List[Dict],
                            test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        以 GT 覆盖为基准进行直接比较（不使用 V-0.5）。

        说明：
        - 仅在 User / GT 两个版本上执行测试并收集覆盖
        - 只统计 source_methods（即本次 diff 变更的被测函数）上的行/分支
        - overlap 以 GT 覆盖集合为分母
        """
        result = {
            'user_coverage': {},
            'gt_coverage': {},
            'gt_reference': {'lines': set(), 'branches': set()},
            'user_covered': {'lines': set(), 'branches': set()},
            'overlap_ratio': {'line': 0.0, 'branch': 0.0},
            'gt_has_reference': False,
            'error': None
        }

        try:
            user_coverage = self._collect_coverage(user_worktree, source_methods, test_methods)
            gt_coverage = self._collect_coverage(gt_worktree, source_methods, test_methods)

            result['user_coverage'] = user_coverage
            result['gt_coverage'] = gt_coverage

            user_lines = self._extract_covered_lines(user_coverage, source_methods)
            gt_lines = self._extract_covered_lines(gt_coverage, source_methods)
            user_branches = self._extract_covered_branches(user_coverage, source_methods)
            gt_branches = self._extract_covered_branches(gt_coverage, source_methods)

            result['user_covered']['lines'] = user_lines
            result['user_covered']['branches'] = user_branches
            result['gt_reference']['lines'] = gt_lines
            result['gt_reference']['branches'] = gt_branches

            result['gt_has_reference'] = bool(gt_lines or gt_branches)

            result['overlap_ratio']['line'] = self._calculate_overlap(user_lines, gt_lines)
            result['overlap_ratio']['branch'] = self._calculate_overlap(user_branches, gt_branches)

            logger.debug(
                f"GT基准覆盖比较: GT行={len(gt_lines)}, User行={len(user_lines)}, "
                f"行重合={result['overlap_ratio']['line']:.2%}; "
                f"GT分支={len(gt_branches)}, User分支={len(user_branches)}, "
                f"分支重合={result['overlap_ratio']['branch']:.2%}"
            )

        except Exception as e:
            logger.error(f"GT基准覆盖比较失败: {e}")
            result['error'] = str(e)

        return result

    def analyze_from_reports(self,
                             v05_report: str,
                             user_report: str,
                             gt_report: str,
                             source_methods: List[Dict]) -> Dict[str, Any]:
        """
        从已有的JaCoCo报告分析覆盖增量

        Args:
            v05_report: V-0.5的JaCoCo报告路径
            user_report: 用户版本的JaCoCo报告路径
            gt_report: GT版本的JaCoCo报告路径
            source_methods: 变更的源代码方法列表

        Returns:
            dict: 同analyze方法
        """
        result = {
            'v05_coverage': {},
            'user_coverage': {},
            'gt_coverage': {},
            'gt_increment': {'lines': set(), 'branches': set()},
            'user_increment': {'lines': set(), 'branches': set()},
            'overlap_ratio': {'line': 0.0, 'branch': 0.0},
            'error': None
        }

        try:
            # 解析报告
            v05_data = self.coverage_analyzer.parse_jacoco_report(v05_report) if os.path.exists(v05_report) else None
            user_data = self.coverage_analyzer.parse_jacoco_report(user_report) if os.path.exists(user_report) else None
            gt_data = self.coverage_analyzer.parse_jacoco_report(gt_report) if os.path.exists(gt_report) else None

            result['v05_coverage'] = {'available': v05_data is not None, 'data': v05_data}
            result['user_coverage'] = {'available': user_data is not None, 'data': user_data}
            result['gt_coverage'] = {'available': gt_data is not None, 'data': gt_data}

            # 计算增量
            v05_lines = self._extract_covered_lines_from_data(v05_data, source_methods) if v05_data else set()
            user_lines = self._extract_covered_lines_from_data(user_data, source_methods) if user_data else set()
            gt_lines = self._extract_covered_lines_from_data(gt_data, source_methods) if gt_data else set()

            gt_increment_lines = gt_lines - v05_lines
            user_increment_lines = user_lines - v05_lines

            result['gt_increment']['lines'] = gt_increment_lines
            result['user_increment']['lines'] = user_increment_lines

            # 计算重合度
            result['overlap_ratio']['line'] = self._calculate_overlap(
                user_increment_lines, gt_increment_lines
            )

        except Exception as e:
            logger.error(f"从报告分析覆盖增量失败: {e}")
            result['error'] = str(e)

        return result

    def _collect_coverage(self,
                          worktree_path: str,
                          source_methods: List[Dict],
                          test_methods: List[Dict] = None) -> Dict[str, Any]:
        """收集worktree的覆盖率"""
        result = {'available': False}

        try:
            jacoco_report = os.path.join(worktree_path, Config.JACOCO_REPORT_PATH)
            jacoco_exec = os.path.join(worktree_path, 'target', 'jacoco.exec')

            # 始终重新执行测试，确保 User 和 GT 两侧使用完全相同的测量条件
            # 删除旧报告及旧的覆盖数据文件，避免复用上次执行结果
            if os.path.exists(jacoco_report):
                os.remove(jacoco_report)
            if os.path.exists(jacoco_exec):
                os.remove(jacoco_exec)

            self._run_test_with_coverage(worktree_path, test_methods)

            if os.path.exists(jacoco_report):
                coverage_data = self.coverage_analyzer.parse_jacoco_report(jacoco_report)
                if coverage_data:
                    result['available'] = True
                    result['data'] = coverage_data

                    # 计算变更方法的覆盖率
                    if source_methods:
                        method_coverage = self.coverage_analyzer.analyze_changed_methods_line_coverage(
                            coverage_data, source_methods
                        )
                        result['method_line_coverage'] = method_coverage

        except Exception as e:
            logger.debug(f"收集覆盖率失败: {e}")
            result['error'] = str(e)

        return result

    def _run_test_with_coverage(self, worktree_path: str,
                               test_methods: List[Dict] = None) -> bool:
        """执行测试并生成覆盖率报告"""
        try:
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            jacoco_version = Config.JACOCO_VERSION

            # 构造 JaCoCo agent 参数（与 ExecutabilityEvaluator 保持一致）
            jacoco_agent_path = (
                '${settings.localRepository}/org/jacoco/org.jacoco.agent/'
                + jacoco_version + '/org.jacoco.agent-' + jacoco_version + '-runtime.jar'
            )
            jacoco_destfile = '${project.build.directory}/jacoco.exec'

            cmd = [
                maven_cmd, 'test', 'jacoco:report', '-B', '-q',
                f'-Djacoco.version={jacoco_version}',
                '-DargLine=-javaagent:' + jacoco_agent_path + '=destfile=' + jacoco_destfile,
                '-Drat.skip=true', '-Denforcer.skip=true', '-Dcheckstyle.skip=true',
                '-Dmaven.test.failure.ignore=true',
                '-Dfelix.skip=true',  # 跳过felix bundle插件避免并发问题
                '-Dmaven.javadoc.skip=true',  # 跳过javadoc
                '-Dmaven.compiler.source=8',  # 覆盖旧版本pom中的Java 1.6设置，确保GT worktree能在现代JDK下编译
                '-Dmaven.compiler.target=8',
                '-Danimal.sniffer.skip=true'  # 跳过API兼容性检查，避免缺失signature包时构建失败
            ]

            # 添加测试选择器（只跑变更测试）
            if test_methods:
                selectors = self._build_test_selectors(test_methods)
                if selectors:
                    cmd.append(f'-Dtest={",".join(selectors)}')
                    cmd.append('-DfailIfNoTests=false')
                    logger.debug(f"覆盖率收集使用测试选择器: {selectors}")

            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                cmd.extend(AnalysisConfig.MAVEN_EXTRA_ARGS.split())

            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"

            subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                timeout=AnalysisConfig.TEST_TIMEOUT,
                env=env
            )

            return True

        except Exception as e:
            logger.debug(f"执行测试失败: {e}")
            return False

    def _build_test_selectors(self, test_methods: List[Dict]) -> List[str]:
        """构建Maven测试选择器（与ExecutabilityEvaluator逻辑一致）"""
        if not test_methods:
            return []

        class_methods = {}

        for method in test_methods:
            class_name = method.get('class')
            package = method.get('package')
            method_name = method.get('method')

            if not class_name:
                continue

            fqcn = f"{package}.{class_name}" if package else class_name

            if method_name:
                class_methods.setdefault(fqcn, set()).add(method_name)
            else:
                class_methods.setdefault(fqcn, set())

        selectors = []
        for fqcn, methods in class_methods.items():
            if methods:
                selector = f"{fqcn}#" + "+".join(sorted(methods))
                selectors.append(selector)
            else:
                selectors.append(fqcn)

        return selectors

    def _extract_covered_lines(self,
                               coverage_result: Dict,
                               source_methods: List[Dict]) -> Set[tuple]:
        """提取变更方法中被覆盖的行"""
        covered_lines = set()

        if not coverage_result.get('available'):
            return covered_lines

        coverage_data = coverage_result.get('data')
        if not coverage_data:
            return covered_lines

        return self._extract_covered_lines_from_data(coverage_data, source_methods)

    def _extract_covered_lines_from_data(self,
                                          coverage_data: Dict,
                                          source_methods: List[Dict]) -> Set[tuple]:
        """从覆盖率数据中提取变更方法的覆盖行"""
        covered_lines = set()

        if not coverage_data:
            return covered_lines

        classes_coverage = coverage_data.get('classes', {})

        for method in source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)
            file_path = method.get('file', '')

            logger.debug(f"分析方法覆盖: {full_class_name}.{method.get('method', '')} (行 {start_line}-{end_line})")

            # 查找类的覆盖信息
            class_cov = classes_coverage.get(full_class_name)
            if not class_cov:
                class_cov = self.coverage_analyzer._fuzzy_match_class(
                    classes_coverage, method.get('class', ''), full_class_name
                )

            if class_cov:
                line_status = class_cov.get('line_status', {})
                for line_no in range(start_line, end_line + 1):
                    if line_status.get(line_no):
                        # 使用 (文件, 类, 行号) 作为唯一标识
                        covered_lines.add((file_path, full_class_name, line_no))
                        logger.debug(f"  覆盖行: {line_no}")
            else:
                logger.debug(f"  未找到类覆盖信息: {full_class_name}")

        return covered_lines

    def _extract_covered_branches(self,
                                   coverage_result: Dict,
                                   source_methods: List[Dict]) -> Set[tuple]:
        """提取变更方法中被覆盖的分支"""
        covered_branches = set()

        if not coverage_result.get('available'):
            return covered_branches

        coverage_data = coverage_result.get('data')
        if not coverage_data:
            return covered_branches

        classes_coverage = coverage_data.get('classes', {})

        for method in source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)
            file_path = method.get('file', '')

            class_cov = classes_coverage.get(full_class_name)
            if not class_cov:
                class_cov = self.coverage_analyzer._fuzzy_match_class(
                    classes_coverage, method.get('class', ''), full_class_name
                )

            if class_cov:
                branch_status = class_cov.get('branch_status', {})
                for line_no in range(start_line, end_line + 1):
                    if line_no in branch_status:
                        info = branch_status[line_no]
                        # 记录每个被覆盖的分支
                        for i in range(info.get('covered', 0)):
                            covered_branches.add((file_path, full_class_name, line_no, i))

        return covered_branches

    def _calculate_overlap(self, user_set: Set, gt_set: Set) -> float:
        """计算重合度"""
        if not gt_set:
            # GT没有增量，返回0.0（无法衡量重合度）
            return 0.0

        intersection = user_set & gt_set
        return len(intersection) / len(gt_set)

    def get_detailed_comparison(self,
                                 user_increment: Set,
                                 gt_increment: Set) -> Dict[str, Any]:
        """获取详细的增量对比"""
        common = user_increment & gt_increment
        user_only = user_increment - gt_increment
        gt_only = gt_increment - user_increment

        return {
            'common_count': len(common),
            'user_only_count': len(user_only),
            'gt_only_count': len(gt_only),
            'gt_total': len(gt_increment),
            'user_total': len(user_increment),
            'overlap_ratio': len(common) / len(gt_increment) if gt_increment else 0.0,
            'common_items': list(common)[:20],  # 限制数量
            'user_only_items': list(user_only)[:20],
            'gt_only_items': list(gt_only)[:20]
        }
