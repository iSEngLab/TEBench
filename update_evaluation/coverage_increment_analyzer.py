"""
Coverage increment analyzer - computes and compares coverage increments
"""

import os
import subprocess
from typing import Dict, Any, List, Set, Optional

from config import Config, AnalysisConfig
from modules.coverage_analyzer import CoverageAnalyzer
from utils.logger import get_logger

logger = get_logger()


class CoverageIncrementAnalyzer:
    """Coverage increment analyzer - computes coverage increments and overlap ratios"""

    def __init__(self):
        """Initialize the coverage increment analyzer"""
        self.coverage_analyzer = CoverageAnalyzer()

    def analyze(self,
                v05_worktree: str,
                user_worktree: str,
                gt_worktree: str,
                source_methods: List[Dict],
                test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        Analyze coverage increments

        Args:
            v05_worktree: worktree path for the V-0.5 version
            user_worktree: worktree path for the user-modified version
            gt_worktree: worktree path for the GT (V0) version
            source_methods: list of changed source code methods
            test_methods: list of test methods to execute (User+GT union), or None to run all

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
            # 1. Collect V-0.5 coverage
            v05_coverage = self._collect_coverage(v05_worktree, source_methods, test_methods)
            result['v05_coverage'] = v05_coverage

            # 2. Collect user version coverage
            user_coverage = self._collect_coverage(user_worktree, source_methods, test_methods)
            result['user_coverage'] = user_coverage

            # 3. Collect GT version coverage
            gt_coverage = self._collect_coverage(gt_worktree, source_methods, test_methods)
            result['gt_coverage'] = gt_coverage

            # 4. Compute increments
            v05_lines = self._extract_covered_lines(v05_coverage, source_methods)
            user_lines = self._extract_covered_lines(user_coverage, source_methods)
            gt_lines = self._extract_covered_lines(gt_coverage, source_methods)

            logger.debug(f"V-0.5 covered lines: {len(v05_lines)}")
            logger.debug(f"User covered lines: {len(user_lines)}")
            logger.debug(f"GT covered lines: {len(gt_lines)}")

            gt_increment_lines = gt_lines - v05_lines
            user_increment_lines = user_lines - v05_lines

            logger.debug(f"GT increment lines: {gt_increment_lines}")
            logger.debug(f"User increment lines: {user_increment_lines}")

            result['gt_increment']['lines'] = gt_increment_lines
            result['user_increment']['lines'] = user_increment_lines

            # 5. Compute branch coverage increments
            v05_branches = self._extract_covered_branches(v05_coverage, source_methods)
            user_branches = self._extract_covered_branches(user_coverage, source_methods)
            gt_branches = self._extract_covered_branches(gt_coverage, source_methods)

            gt_increment_branches = gt_branches - v05_branches
            user_increment_branches = user_branches - v05_branches

            result['gt_increment']['branches'] = gt_increment_branches
            result['user_increment']['branches'] = user_increment_branches

            # Mark whether GT has an increment
            result['gt_has_increment'] = bool(gt_increment_lines or gt_increment_branches)

            # 6. Compute overlap ratio
            result['overlap_ratio']['line'] = self._calculate_overlap(
                user_increment_lines, gt_increment_lines
            )
            result['overlap_ratio']['branch'] = self._calculate_overlap(
                user_increment_branches, gt_increment_branches
            )

            logger.debug(f"Coverage increment analysis: GT increment lines={len(gt_increment_lines)}, "
                        f"User increment lines={len(user_increment_lines)}, "
                        f"line overlap={result['overlap_ratio']['line']:.2%}, "
                        f"GT has increment={result['gt_has_increment']}")

        except Exception as e:
            logger.error(f"Coverage increment analysis failed: {e}")
            result['error'] = str(e)

        return result

    def analyze_gt_baseline(self,
                            user_worktree: str,
                            gt_worktree: str,
                            source_methods: List[Dict],
                            test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        Direct comparison using GT coverage as baseline (without V-0.5).

        Description:
        - Runs tests only on the User / GT versions and collects coverage
        - Only counts lines/branches on source_methods (i.e., source functions changed in this diff)
        - Overlap uses GT coverage set as denominator
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
                f"GT baseline coverage comparison: GT lines={len(gt_lines)}, User lines={len(user_lines)}, "
                f"line overlap={result['overlap_ratio']['line']:.2%}; "
                f"GT branches={len(gt_branches)}, User branches={len(user_branches)}, "
                f"branch overlap={result['overlap_ratio']['branch']:.2%}"
            )

        except Exception as e:
            logger.error(f"GT baseline coverage comparison failed: {e}")
            result['error'] = str(e)

        return result

    def analyze_from_reports(self,
                             v05_report: str,
                             user_report: str,
                             gt_report: str,
                             source_methods: List[Dict]) -> Dict[str, Any]:
        """
        Analyze coverage increments from existing JaCoCo reports

        Args:
            v05_report: JaCoCo report path for V-0.5
            user_report: JaCoCo report path for the user version
            gt_report: JaCoCo report path for the GT version
            source_methods: list of changed source code methods

        Returns:
            dict: same structure as analyze()
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
            # Parse reports
            v05_data = self.coverage_analyzer.parse_jacoco_report(v05_report) if os.path.exists(v05_report) else None
            user_data = self.coverage_analyzer.parse_jacoco_report(user_report) if os.path.exists(user_report) else None
            gt_data = self.coverage_analyzer.parse_jacoco_report(gt_report) if os.path.exists(gt_report) else None

            result['v05_coverage'] = {'available': v05_data is not None, 'data': v05_data}
            result['user_coverage'] = {'available': user_data is not None, 'data': user_data}
            result['gt_coverage'] = {'available': gt_data is not None, 'data': gt_data}

            # Compute increments
            v05_lines = self._extract_covered_lines_from_data(v05_data, source_methods) if v05_data else set()
            user_lines = self._extract_covered_lines_from_data(user_data, source_methods) if user_data else set()
            gt_lines = self._extract_covered_lines_from_data(gt_data, source_methods) if gt_data else set()

            gt_increment_lines = gt_lines - v05_lines
            user_increment_lines = user_lines - v05_lines

            result['gt_increment']['lines'] = gt_increment_lines
            result['user_increment']['lines'] = user_increment_lines

            # Compute overlap ratio
            result['overlap_ratio']['line'] = self._calculate_overlap(
                user_increment_lines, gt_increment_lines
            )

        except Exception as e:
            logger.error(f"Failed to analyze coverage increments from reports: {e}")
            result['error'] = str(e)

        return result

    def _collect_coverage(self,
                          worktree_path: str,
                          source_methods: List[Dict],
                          test_methods: List[Dict] = None) -> Dict[str, Any]:
        """Collect coverage for a worktree"""
        result = {'available': False}

        try:
            jacoco_report = os.path.join(worktree_path, Config.JACOCO_REPORT_PATH)
            jacoco_exec = os.path.join(worktree_path, 'target', 'jacoco.exec')

            # Always re-run tests to ensure User and GT sides use identical measurement conditions
            # Delete old report and coverage data files to avoid reusing previous execution results
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

                    # Compute coverage for changed methods
                    if source_methods:
                        method_coverage = self.coverage_analyzer.analyze_changed_methods_line_coverage(
                            coverage_data, source_methods
                        )
                        result['method_line_coverage'] = method_coverage

        except Exception as e:
            logger.debug(f"Failed to collect coverage: {e}")
            result['error'] = str(e)

        return result

    def _run_test_with_coverage(self, worktree_path: str,
                               test_methods: List[Dict] = None) -> bool:
        """Run tests and generate a coverage report"""
        try:
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            jacoco_version = Config.JACOCO_VERSION

            # Build JaCoCo agent arguments (consistent with ExecutabilityEvaluator)
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
                '-Dfelix.skip=true',  # skip felix bundle plugin to avoid concurrency issues
                '-Dmaven.javadoc.skip=true',  # skip javadoc
                '-Dmaven.compiler.source=8',  # override Java 1.6 setting in older POMs so GT worktree compiles with modern JDK
                '-Dmaven.compiler.target=8',
                '-Danimal.sniffer.skip=true'  # skip API compatibility check to avoid build failure when signature package is missing
            ]

            # Add test selectors (only run changed tests)
            if test_methods:
                selectors = self._build_test_selectors(test_methods)
                if selectors:
                    cmd.append(f'-Dtest={",".join(selectors)}')
                    cmd.append('-DfailIfNoTests=false')
                    logger.debug(f"Coverage collection using test selectors: {selectors}")

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
            logger.debug(f"Test execution failed: {e}")
            return False

    def _build_test_selectors(self, test_methods: List[Dict]) -> List[str]:
        """Build Maven test selectors (same logic as ExecutabilityEvaluator)"""
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
        """Extract covered lines within changed methods"""
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
        """Extract covered lines for changed methods from coverage data"""
        covered_lines = set()

        if not coverage_data:
            return covered_lines

        classes_coverage = coverage_data.get('classes', {})

        for method in source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)
            file_path = method.get('file', '')

            logger.debug(f"Analyzing method coverage: {full_class_name}.{method.get('method', '')} (lines {start_line}-{end_line})")

            # Look up class coverage info
            class_cov = classes_coverage.get(full_class_name)
            if not class_cov:
                class_cov = self.coverage_analyzer._fuzzy_match_class(
                    classes_coverage, method.get('class', ''), full_class_name
                )

            if class_cov:
                line_status = class_cov.get('line_status', {})
                for line_no in range(start_line, end_line + 1):
                    if line_status.get(line_no):
                        # Use (file, class, line_number) as unique identifier
                        covered_lines.add((file_path, full_class_name, line_no))
                        logger.debug(f"  Covered line: {line_no}")
            else:
                logger.debug(f"  Class coverage info not found: {full_class_name}")

        return covered_lines

    def _extract_covered_branches(self,
                                   coverage_result: Dict,
                                   source_methods: List[Dict]) -> Set[tuple]:
        """Extract covered branches within changed methods"""
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
                        # Record each covered branch
                        for i in range(info.get('covered', 0)):
                            covered_branches.add((file_path, full_class_name, line_no, i))

        return covered_branches

    def _calculate_overlap(self, user_set: Set, gt_set: Set) -> float:
        """Calculate overlap ratio"""
        if not gt_set:
            # GT has no increment; return 0.0 (overlap cannot be measured)
            return 0.0

        intersection = user_set & gt_set
        return len(intersection) / len(gt_set)

    def get_detailed_comparison(self,
                                 user_increment: Set,
                                 gt_increment: Set) -> Dict[str, Any]:
        """Get a detailed increment comparison"""
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
            'common_items': list(common)[:20],  # limit count
            'user_only_items': list(user_only)[:20],
            'gt_only_items': list(gt_only)[:20]
        }
