"""
可执行性评估器 - 评估用户修改后的测试是否可执行
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
    """可执行性评估器 - 评估测试的编译和执行情况"""

    def __init__(self):
        """初始化可执行性评估器"""
        pass

    def evaluate(self,
                 worktree_path: str,
                 changed_test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        评估worktree中代码的可执行性

        Args:
            worktree_path: worktree路径
            changed_test_methods: 变更的测试方法列表（用于选择性执行）

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
            # 1. 检查pom.xml
            pom_path = os.path.join(worktree_path, 'pom.xml')
            if not os.path.exists(pom_path):
                result['compile_error'] = "pom.xml not found"
                return result

            # 2. 执行编译
            compile_result = self._run_compile(worktree_path)
            result['compile_success'] = compile_result['success']

            if not compile_result['success']:
                result['compile_error'] = compile_result.get('error')
                return result

            # 3. 执行测试
            logger.debug("开始执行测试...")
            test_selectors = self._build_test_selectors(changed_test_methods)

            if not test_selectors:
                # 没有具体的测试方法可运行（如GT只修改了private helper），
                # 跳过全量测试以避免无关失败，视为"编译通过无可运行测试"
                logger.debug("无测试选择器，跳过全量测试执行")
                result['test_success'] = True
            else:
                test_result = self._run_test(worktree_path, test_selectors)
                logger.debug(f"测试执行完成: {test_result}")

                result['test_success'] = test_result['success']
                result['test_results'] = test_result.get('summary', result['test_results'])
                result['failed_tests'] = test_result.get('failed_tests', [])
                result['test_error'] = test_result.get('error')

        except Exception as e:
            logger.error(f"可执行性评估失败: {e}")
            result['test_error'] = str(e)

        finally:
            result['duration_seconds'] = (datetime.now() - start_time).total_seconds()

        return result

    def _run_compile(self, worktree_path: str) -> Dict[str, Any]:
        """执行Maven编译"""
        result = {'success': False, 'error': None}

        try:
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            # 跳过 RAT 检查和其他非必要的检查
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
        """执行Maven测试"""
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
            # 跳过 RAT 检查和其他非必要的检查
            cmd = [maven_cmd, 'test', 'jacoco:report', '-B',
                   '-Drat.skip=true', '-Denforcer.skip=true', '-Dcheckstyle.skip=true',
                   '-Dmaven.test.failure.ignore=true',
                   '-Dfelix.skip=true',  # 跳过felix bundle插件避免并发问题
                   '-Dmaven.javadoc.skip=true']  # 跳过javadoc

            # 添加JaCoCo用于覆盖率收集
            # 注意：Maven变量使用${}格式，需要用普通字符串避免Python解析
            jacoco_version = Config.JACOCO_VERSION
            jacoco_agent_path = '${settings.localRepository}/org/jacoco/org.jacoco.agent/' + \
                                jacoco_version + '/org.jacoco.agent-' + jacoco_version + '-runtime.jar'
            jacoco_destfile = '${project.build.directory}/jacoco.exec'
            cmd.extend([
                '-Djacoco.version=' + jacoco_version,
                '-DargLine=-javaagent:' + jacoco_agent_path + '=destfile=' + jacoco_destfile
            ])

            # 添加测试选择器
            if test_selectors:
                cmd.append(f'-Dtest={",".join(test_selectors)}')
                cmd.append('-DfailIfNoTests=false')  # 如果没有匹配的测试不要失败
                logger.debug(f"使用测试选择器: {test_selectors}")
            else:
                logger.debug("运行所有测试")

            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                cmd.extend(AnalysisConfig.MAVEN_EXTRA_ARGS.split())

            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"

            logger.debug(f"执行命令: {' '.join(cmd)}")

            process = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=AnalysisConfig.TEST_TIMEOUT,
                env=env
            )

            # 合并stdout和stderr进行解析
            full_output = (process.stdout or '') + '\n' + (process.stderr or '')

            # 解析测试结果
            summary = self._parse_test_summary(full_output)
            if summary['total'] == 0:
                # 尝试从报告解析
                report_summary = self._parse_test_summary_from_reports(worktree_path)
                if report_summary:
                    summary = report_summary
                else:
                    logger.warning(f"无法解析测试结果")
                    logger.debug(f"Maven输出: {full_output[-1000:] if full_output else 'empty'}")

            result['summary'] = summary
            logger.debug(f"测试结果: {summary}")

            # 判断成功
            if summary['failed'] == 0 and summary['errors'] == 0 and summary['total'] > 0:
                result['success'] = True
            elif summary['total'] == 0 and process.returncode == 0:
                result['success'] = True  # 没有测试但编译通过

            # 解析失败的测试
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
        """构建Maven测试选择器"""
        if not changed_test_methods:
            logger.debug("没有变更的测试方法，将运行所有测试")
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

        logger.debug(f"构建测试选择器: {selectors}")
        return selectors

    def _parse_test_summary(self, output: str) -> Dict[str, int]:
        """解析测试摘要"""
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
        """从Surefire报告解析测试摘要"""
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
        """解析失败的测试"""
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
        """提取错误信息"""
        lines = output.split('\n')
        error_lines = []

        for line in lines:
            if '[ERROR]' in line or 'error:' in line.lower():
                error_lines.append(line.strip())

        if error_lines:
            return '\n'.join(error_lines[:10])

        return "Unknown error"
