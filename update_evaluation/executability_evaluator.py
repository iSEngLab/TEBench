"""
Executability evaluator - evaluates whether tests are executable after user modifications
"""

import os
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional
import xml.etree.ElementTree as ET

from config import Config, AnalysisConfig
from utils.logger import get_logger

logger = get_logger()


class ExecutabilityEvaluator:
    """Executability evaluator - evaluates test compilation and execution"""

    def __init__(self):
        """Initialize the executability evaluator"""
        pass

    def evaluate(self,
                 worktree_path: str,
                 changed_test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        Evaluate the executability of code in a worktree

        Args:
            worktree_path: worktree path
            changed_test_methods: list of changed test methods (for selective execution)

        Returns:
            dict: {
                'compile_success': bool,
                'test_success': bool,
                'test_results': {
                    'total': int,
                    'passed': int,
                    'failed': int,
                    'errors': int,
                    'skipped': int
                },
                'failed_tests': [...],
                'compile_error': str,
                'test_error': str,
                'duration_seconds': float
            }
        """
        result = {
            'compile_success': False,
            'test_success': False,
            'test_results': {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'errors': 0,
                'skipped': 0
            },
            'failed_tests': [],
            'compile_error': None,
            'test_error': None,
            'duration_seconds': 0
        }

        start_time = datetime.now()

        try:
            # 1. Check pom.xml
            pom_path = os.path.join(worktree_path, 'pom.xml')
            if not os.path.exists(pom_path):
                result['compile_error'] = "pom.xml not found"
                return result

            # 2. Run compilation
            compile_result = self._run_compile(worktree_path)
            result['compile_success'] = compile_result['success']

            if not compile_result['success']:
                result['compile_error'] = compile_result.get('error')
                return result

            # 3. Run tests
            logger.debug("Starting test execution...")
            test_selectors = self._build_test_selectors(changed_test_methods)

            if not test_selectors:
                # No specific test methods to run (e.g., GT only modified private helpers),
                # skip full test run to avoid unrelated failures, treat as "compile success, no runnable tests"
                logger.debug("No test selectors, skipping full test execution")
                result['test_success'] = True
            else:
                test_result = self._run_test(worktree_path, test_selectors)
                logger.debug(f"Test execution completed: {test_result}")

                result['test_success'] = test_result['success']
                result['test_results'] = test_result.get('summary', result['test_results'])
                result['failed_tests'] = test_result.get('failed_tests', [])
                result['test_error'] = test_result.get('error')

        except Exception as e:
            logger.error(f"Executability evaluation failed: {e}")
            result['test_error'] = str(e)

        finally:
            result['duration_seconds'] = (datetime.now() - start_time).total_seconds()

        return result

    def _run_compile(self, worktree_path: str) -> Dict[str, Any]:
        """Run Maven compilation"""
        result = {'success': False, 'error': None}

        try:
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            # Skip RAT check and other non-essential checks
            cmd = [maven_cmd, 'compile', '-DskipTests', '-Drat.skip=true',
                   '-Denforcer.skip=true', '-Dcheckstyle.skip=true', '-B', '-q']

            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                cmd.extend(AnalysisConfig.MAVEN_EXTRA_ARGS.split())

            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"

            process = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=AnalysisConfig.COMPILE_TIMEOUT,
                env=env
            )

            if process.returncode == 0:
                result['success'] = True
            else:
                result['error'] = self._extract_error(process.stderr or process.stdout)

        except subprocess.TimeoutExpired:
            result['error'] = f"Compilation timed out after {AnalysisConfig.COMPILE_TIMEOUT}s"
        except Exception as e:
            result['error'] = str(e)

        return result

    def _run_test(self,
                  worktree_path: str,
                  test_selectors: List[str] = None) -> Dict[str, Any]:
        """Run Maven tests"""
        result = {
            'success': False,
            'summary': {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'errors': 0,
                'skipped': 0
            },
            'failed_tests': [],
            'error': None
        }

        try:
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            # Skip RAT check and other non-essential checks
            cmd = [maven_cmd, 'test', 'jacoco:report', '-B',
                   '-Drat.skip=true', '-Denforcer.skip=true', '-Dcheckstyle.skip=true',
                   '-Dmaven.test.failure.ignore=true',
                   '-Dfelix.skip=true',  # skip felix bundle plugin to avoid concurrency issues
                   '-Dmaven.javadoc.skip=true']  # skip javadoc

            # Add JaCoCo for coverage collection
            # Note: Maven variables use ${} format; use plain strings to avoid Python interpolation
            jacoco_version = Config.JACOCO_VERSION
            jacoco_agent_path = '${settings.localRepository}/org/jacoco/org.jacoco.agent/' + \
                                jacoco_version + '/org.jacoco.agent-' + jacoco_version + '-runtime.jar'
            jacoco_destfile = '${project.build.directory}/jacoco.exec'
            cmd.extend([
                '-Djacoco.version=' + jacoco_version,
                '-DargLine=-javaagent:' + jacoco_agent_path + '=destfile=' + jacoco_destfile
            ])

            # Add test selectors
            if test_selectors:
                cmd.append(f'-Dtest={",".join(test_selectors)}')
                cmd.append('-DfailIfNoTests=false')  # do not fail if no matching tests
                logger.debug(f"Using test selectors: {test_selectors}")
            else:
                logger.debug("Running all tests")

            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                cmd.extend(AnalysisConfig.MAVEN_EXTRA_ARGS.split())

            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"

            logger.debug(f"Executing command: {' '.join(cmd)}")

            process = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=AnalysisConfig.TEST_TIMEOUT,
                env=env
            )

            # Combine stdout and stderr for parsing
            full_output = (process.stdout or '') + '\n' + (process.stderr or '')

            # Parse test results
            summary = self._parse_test_summary(full_output)
            if summary['total'] == 0:
                # Try parsing from reports
                report_summary = self._parse_test_summary_from_reports(worktree_path)
                if report_summary:
                    summary = report_summary
                else:
                    logger.warning(f"Unable to parse test results")
                    logger.debug(f"Maven output: {full_output[-1000:] if full_output else 'empty'}")

            result['summary'] = summary
            logger.debug(f"Test results: {summary}")

            # Determine success
            if summary['failed'] == 0 and summary['errors'] == 0 and summary['total'] > 0:
                result['success'] = True
            elif summary['total'] == 0 and process.returncode == 0:
                result['success'] = True  # no tests but compilation passed

            # Parse failed tests
            if summary['failed'] > 0 or summary['errors'] > 0:
                result['failed_tests'] = self._parse_failed_tests(worktree_path)

            if process.returncode != 0 and not result['success']:
                result['error'] = self._extract_error(process.stderr or process.stdout)

        except subprocess.TimeoutExpired:
            result['error'] = f"Test timed out after {AnalysisConfig.TEST_TIMEOUT}s"
        except Exception as e:
            result['error'] = str(e)

        return result

    def _build_test_selectors(self, changed_test_methods: List[Dict]) -> List[str]:
        """Build Maven test selectors"""
        if not changed_test_methods:
            logger.debug("No changed test methods; all tests will be run")
            return []

        class_methods = {}

        for method in changed_test_methods:
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

        logger.debug(f"Built test selectors: {selectors}")
        return selectors

    def _parse_test_summary(self, output: str) -> Dict[str, int]:
        """Parse test summary"""
        import re

        result = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'errors': 0,
            'skipped': 0
        }

        pattern = r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)'
        matches = re.findall(pattern, output)

        if matches:
            for match in matches:
                result['total'] += int(match[0])
                result['failed'] += int(match[1])
                result['errors'] += int(match[2])
                result['skipped'] += int(match[3])

            result['passed'] = result['total'] - result['failed'] - result['errors'] - result['skipped']

        return result

    def _parse_test_summary_from_reports(self, worktree_path: str) -> Optional[Dict[str, int]]:
        """Parse test summary from Surefire reports"""
        surefire_dir = os.path.join(worktree_path, 'target', 'surefire-reports')
        if not os.path.exists(surefire_dir):
            return None

        totals = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'errors': 0,
            'skipped': 0
        }
        parsed_any = False

        for filename in os.listdir(surefire_dir):
            if not (filename.startswith('TEST-') and filename.endswith('.xml')):
                continue

            filepath = os.path.join(surefire_dir, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()

                tests = int(root.get('tests', 0))
                failures = int(root.get('failures', 0))
                errors = int(root.get('errors', 0))
                skipped = int(root.get('skipped', 0))

                totals['total'] += tests
                totals['failed'] += failures
                totals['errors'] += errors
                totals['skipped'] += skipped
                parsed_any = True

            except Exception:
                continue

        if not parsed_any:
            return None

        totals['passed'] = totals['total'] - totals['failed'] - totals['errors'] - totals['skipped']
        return totals

    def _parse_failed_tests(self, worktree_path: str) -> List[Dict]:
        """Parse failed tests"""
        failed_tests = []
        surefire_dir = os.path.join(worktree_path, 'target', 'surefire-reports')

        if not os.path.exists(surefire_dir):
            return failed_tests

        for filename in os.listdir(surefire_dir):
            if not (filename.startswith('TEST-') and filename.endswith('.xml')):
                continue

            filepath = os.path.join(surefire_dir, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()

                for testcase in root.findall('.//testcase'):
                    failure = testcase.find('failure')
                    error = testcase.find('error')

                    if failure is not None or error is not None:
                        elem = failure if failure is not None else error
                        failed_tests.append({
                            'class': testcase.get('classname'),
                            'method': testcase.get('name'),
                            'full_name': f"{testcase.get('classname')}.{testcase.get('name')}",
                            'failure_type': elem.get('type'),
                            'message': elem.get('message', '')[:500]
                        })

            except Exception:
                continue

        return failed_tests[:50]

    def _extract_error(self, output: str) -> str:
        """Extract error information"""
        lines = output.split('\n')
        error_lines = []

        for line in lines:
            if '[ERROR]' in line or 'error:' in line.lower():
                error_lines.append(line.strip())

        if error_lines:
            return '\n'.join(error_lines[:10])

        return "Unknown error"
