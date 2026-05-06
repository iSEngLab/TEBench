"""
Isolated executor - runs builds and tests in a temporary worktree without polluting the original repository
Uses approach B: temporary worktree + patch application, deleted after analysis
"""

import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from typing import Optional, Dict, Any

from git import Repo, GitCommandError
from config import Config, AnalysisConfig
from utils.logger import get_logger
from modules.maven_executor import MavenExecutor
from modules.coverage_analyzer import CoverageAnalyzer
from modules.code_analyzer import CodeAnalyzer

logger = get_logger()


class IsolatedExecutor:
    """Isolated executor - ensures the original repository is not polluted"""
    
    def __init__(self, repo_path: str, work_dir: str = None):
        """
        Initialize isolated executor
        
        Args:
            repo_path: original repository path
            work_dir: working directory, defaults to temporary directory
        """
        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        
        # thread-local storage, creates an independent Repo instance per thread
        self._thread_local = threading.local()
        
        # Work directory (isolate by PID to avoid cross-process cleanup collisions)
        base_dir = work_dir or AnalysisConfig.ANALYSIS_WORKTREE_DIR
        self.work_dir = os.path.join(base_dir, f"{self.project_name}_{os.getpid()}")
        os.makedirs(self.work_dir, exist_ok=True)
        
        # track created worktrees for cleanup (requires thread safety)
        self._created_worktrees = []
        self._worktrees_lock = threading.Lock()
        
        # coverage analyzer
        self.coverage_analyzer = CoverageAnalyzer()
    
    @property
    def repo(self) -> Repo:
        """get the Repo instance for the current thread (thread-safe)"""
        if not hasattr(self._thread_local, 'repo'):
            self._thread_local.repo = Repo(self.repo_path)
        return self._thread_local.repo
    
    def execute_version(self,
                       commit_hash: str,
                       version_type: str,
                       patch_content: str = None,
                       changed_source_methods: Optional[list] = None,
                       changed_test_methods: Optional[list] = None) -> Dict[str, Any]:
        """
        execute a specified version in an isolated environment
        
        Args:
            commit_hash: base commit hash (for v05/t05, this is parent_hash)
            version_type: version type ('v1', 'v05', 't05', 'v0')
            patch_content: patch to apply (required for v05 and t05)
            
        Returns:
            execution result dictionary
        """
        result = {
            'version': version_type,
            'commit_used': commit_hash,
            'build': {'success': False},
            'test': {'success': False},
            'coverage': {'available': False}
        }
        
        # generateworktree path
        worktree_path = self._get_worktree_path(commit_hash, version_type)
        
        try:
            # 1. createworktree
            if not self._create_worktree(commit_hash, worktree_path):
                result['build']['error_message'] = "Failed to create worktree"
                return result
            
            result['worktree_path'] = worktree_path
            
            # 2. Apply patch (if needed)
            if patch_content and version_type in ('v05', 't05'):
                patch_result = self._apply_patch(patch_content, worktree_path)
                result['patch_applied'] = patch_result['success']
                
                if not patch_result['success']:
                    result['build']['error_message'] = f"Failed to apply patch: {patch_result.get('error')}"
                    return result
            
            # 3. executecompile
            build_result = self._run_maven_compile(worktree_path)
            result['build'] = build_result
            
            if not build_result['success']:
                return result
            
            # 4. Run tests
            test_result = self._run_maven_test(worktree_path, changed_test_methods)
            result['test'] = test_result
            
            # 5. Collect coverage (attempt regardless of test success)
            if build_result['success']:
                coverage_result = self._collect_coverage(
                    worktree_path,
                    changed_source_methods=changed_source_methods,
                    changed_test_methods=changed_test_methods
                )
                result['coverage'] = coverage_result
            
        except Exception as e:
            logger.error(f"executeversion {version_type} Failed: {e}")
            result['error'] = str(e)
        
        finally:
            # clean upworktree
            self._cleanup_worktree(worktree_path)
        
        return result
    
    def _get_worktree_path(self, commit_hash: str, version_type: str) -> str:
        """generateworktree path"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return os.path.join(
            self.work_dir,
            f"{self.project_name}_{commit_hash[:8]}_{version_type}_{timestamp}"
        )
    
    def _create_worktree(self, commit_hash: str, worktree_path: str) -> bool:
        """creategit worktree"""
        try:
            # Ensure path does not exist
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path)
            
            # createworktree
            self.repo.git.worktree('add', '--detach', worktree_path, commit_hash)
            
            with self._worktrees_lock:
                self._created_worktrees.append(worktree_path)
            logger.debug(f"createworktree: {worktree_path}")
            return True
            
        except GitCommandError as e:
            logger.error(f"createworktreeFailed: {e}")
            return False
    
    def _apply_patch(self, patch_content: str, worktree_path: str) -> Dict[str, Any]:
        """apply patch to worktree"""
        result = {'success': False}
        
        if not patch_content or not patch_content.strip():
            result['success'] = True
            result['message'] = "Empty patch, nothing to apply"
            return result
        
        patch_file = os.path.join(worktree_path, '.tubench_patch.diff')

        try:
            # Write patch to temporary file
            # Ensure patch ends with newline to avoid "corrupt patch" from git apply
            if not patch_content.endswith('\n'):
                patch_content = patch_content + '\n'
            with open(patch_file, 'w', encoding='utf-8') as f:
                f.write(patch_content)

            # Apply patch
            process = subprocess.run(
                ['git', 'apply', '--verbose', patch_file],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=60
            )

            if process.returncode == 0:
                result['success'] = True
                result['output'] = process.stdout
            else:
                # Try using --3way option
                process2 = subprocess.run(
                    ['git', 'apply', '--3way', patch_file],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if process2.returncode == 0:
                    result['success'] = True
                else:
                    result['error'] = process.stderr or process2.stderr
                    logger.debug(f"Patch application failed: {result['error']}")

        except subprocess.TimeoutExpired:
            result['error'] = "Patch application timed out"
        except Exception as e:
            result['error'] = str(e)
        finally:
            # clean uppatchfile
            if os.path.exists(patch_file):
                try:
                    os.remove(patch_file)
                except Exception:
                    pass
        
        return result
    
    def _run_maven_compile(self, worktree_path: str) -> Dict[str, Any]:

        result = {
            'success': False,
            'duration_seconds': 0,
            'command': 'mvn compile -DskipTests'
        }
        
        start_time = datetime.now()
        
        try:
            # Check if pom.xml exists
            pom_path = os.path.join(worktree_path, 'pom.xml')
            if not os.path.exists(pom_path):
                result['error_message'] = "pom.xml not found"
                return result
            
            # Build Maven command
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or 'mvn'
            cmd = [maven_cmd, 'compile', '-DskipTests', '-B', '-q']
            
            # Add extra Maven options
            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                extra_args = AnalysisConfig.MAVEN_EXTRA_ARGS.split()
                cmd.extend(extra_args)
            
            # Build environment variables
            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"
            
            # executecompile
            process = subprocess.run(
                cmd,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=AnalysisConfig.COMPILE_TIMEOUT,
                env=env
            )
            
            result['return_code'] = process.returncode
            result['stdout'] = process.stdout[-5000:] if len(process.stdout) > 5000 else process.stdout
            result['stderr'] = process.stderr[-5000:] if len(process.stderr) > 5000 else process.stderr
            
            if process.returncode == 0:
                result['success'] = True
            else:
                error_output = process.stderr or process.stdout
                result['error_message'] = self._extract_compile_error(error_output)
                result['compile_errors'] = self._parse_compile_errors(error_output)
                
                # Detect if this is a compatibility issue
                compat_issues = self._detect_compatibility_issues(error_output)
                if compat_issues:
                    result['compatibility_issues'] = compat_issues
                    if AnalysisConfig.SKIP_INCOMPATIBLE_COMMITS:
                        result['skip_reason'] = "compatibility_issue"
                
        except subprocess.TimeoutExpired:
            result['error_message'] = f"Compilation timed out after {AnalysisConfig.COMPILE_TIMEOUT}s"
        except Exception as e:
            result['error_message'] = str(e)
        
        result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
        return result
    
    def _run_maven_test(self, worktree_path: str, changed_test_methods: Optional[list] = None) -> Dict[str, Any]:
        """Execute Maven tests and collect coverage"""
        result = {
            'success': False,
            'duration_seconds': 0,
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0,
            'failed_tests': [],
            'error_tests': []
        }
        result['selection_skipped'] = False
        
        start_time = datetime.now()
        
        try:
            # Run tests with JaCoCo
            maven_executor = MavenExecutor(worktree_path)
            selected_tests = self._build_test_selectors(worktree_path, changed_test_methods)
            if changed_test_methods is not None and not selected_tests:
                result['selection_skipped'] = True
                result['status'] = 'skip'
                result['error_message'] = "No changed tests identified"
                result['selected_tests'] = []
                result['success'] = False
                return result

            test_result = maven_executor.test_with_jacoco(selected_tests=selected_tests)
            
            result['return_code'] = test_result.get('return_code', -1)
            test_output = test_result.get('stdout', '') or ''
            test_error_output = test_result.get('stderr', '') or ''
            result['stdout'] = test_output[-5000:]
            result['stderr'] = test_error_output[-5000:]
            result['selected_tests'] = selected_tests
            
            # Parse test results
            test_summary = self._parse_test_summary(test_output)
            if test_summary.get('total_tests', 0) == 0:
                report_summary = self._parse_test_summary_from_reports(worktree_path)
                if report_summary:
                    test_summary = report_summary
            result.update(test_summary)
            
            if (result.get('failed', 0) > 0) or (result.get('errors', 0) > 0):
                failed_tests = self._parse_failed_tests(worktree_path)
                result['failed_tests'] = failed_tests

            # detect
            compile_error = self._detect_test_compile_error(test_output)
            if compile_error:
                result['error_type'] = 'test_compile'
                if not result.get('error_message'):
                    result['error_message'] = compile_error

            status, reason = self._derive_test_status(result)
            result['status'] = status
            result['success'] = status == 'pass'
            if reason and not result.get('error_message'):
                result['error_message'] = reason
                
        except subprocess.TimeoutExpired:
            result['error_message'] = f"Test timed out after {AnalysisConfig.TEST_TIMEOUT}s"
            result['status'] = 'error'
        except Exception as e:
            result['error_message'] = str(e)
            result['status'] = 'error'
        
        result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
        return result

    def _build_test_selectors(self, worktree_path: str, changed_test_methods: Optional[list]) -> list:
        
        if not changed_test_methods:
            return []

        class_methods = {}
        class_only = set()
        resolved = self._resolve_changed_methods(worktree_path, changed_test_methods)
        resolved_keys = {
            (m.get('file'), m.get('class'), m.get('method'))
            for m in resolved
        }
        use_resolved = len(resolved_keys) > 0

        for method in changed_test_methods:
            class_name = method.get('class')
            package = method.get('package')
            method_name = method.get('method')
            is_test = method.get('is_test_method', False)
            file_path = method.get('file')

            if not class_name:
                continue

            if file_path:
                abs_path = os.path.join(worktree_path, file_path)
                if not os.path.exists(abs_path):
                    continue

            if use_resolved and (file_path, class_name, method_name) not in resolved_keys:
                continue

            fqcn = f"{package}.{class_name}" if package else class_name

            if is_test and method_name:
                class_methods.setdefault(fqcn, set()).add(method_name)
            else:
                class_only.add(fqcn)

        selectors = []
        for fqcn, methods in class_methods.items():
            if methods:
                selector = f"{fqcn}#" + "+".join(sorted(methods))
                selectors.append(selector)

        for fqcn in sorted(class_only):
            if fqcn not in class_methods:
                selectors.append(fqcn)

        return selectors
    
    def _collect_coverage(self,
                          worktree_path: str,
                          changed_source_methods: Optional[list] = None,
                          changed_test_methods: Optional[list] = None) -> Dict[str, Any]:
        """collect coverageinformation"""
        result = {'available': False}
        
        try:
            jacoco_report = os.path.join(worktree_path, Config.JACOCO_REPORT_PATH)
            
            if os.path.exists(jacoco_report):
                coverage_data = self.coverage_analyzer.parse_jacoco_report(jacoco_report)
                
                if coverage_data:
                    result['available'] = True
                    result['jacoco_report_path'] = jacoco_report
                    if changed_source_methods:
                        resolved_methods = self._resolve_changed_methods(
                            worktree_path,
                            changed_source_methods
                        )
                        method_coverage = self.coverage_analyzer.analyze_test_coverage_for_changes(
                            coverage_data,
                            changed_test_methods or [],
                            resolved_methods
                        )
                        result['method_coverage'] = method_coverage

                        method_line_coverage = self.coverage_analyzer.analyze_changed_methods_line_coverage(
                            coverage_data,
                            resolved_methods
                        )
                        result['method_line_coverage'] = method_line_coverage

                        method_branch_coverage = self.coverage_analyzer.analyze_changed_methods_branch_coverage(
                            coverage_data,
                            resolved_methods
                        )
                        result['method_branch_coverage'] = method_branch_coverage

        except Exception as e:
            logger.debug(f"collect coverageFailed: {e}")
            result['error'] = str(e)
        
        return result

    def _resolve_changed_methods(self, worktree_path: str, changed_methods: list) -> list:
        
        if not changed_methods:
            return []

        code_analyzer = CodeAnalyzer()
        resolved = []
        parsed_cache = {}

        for method in changed_methods:
            file_rel_path = method.get('file')
            if not file_rel_path:
                continue

            file_path = os.path.join(worktree_path, file_rel_path)
            if not os.path.exists(file_path):
                continue

            if file_path not in parsed_cache:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    parsed_cache[file_path] = code_analyzer.parse_java_file(content)
                except Exception:
                    parsed_cache[file_path] = {'classes': []}

            classes_info = parsed_cache[file_path]
            class_name = method.get('class')
            method_name = method.get('method')
            parameters = method.get('parameters', [])

            class_methods = []
            for class_info in classes_info.get('classes', []):
                if class_info.get('name') == class_name:
                    class_methods = class_info.get('methods', [])
                    break

            if not class_methods:
                continue

            candidates = [m for m in class_methods if m.get('name') == method_name]
            if not candidates:
                continue

            chosen = None
            if parameters:
                exact = [m for m in candidates if m.get('parameters', []) == parameters]
                if exact:
                    chosen = exact[0]
                else:
                    param_count = len(parameters)
                    by_count = [m for m in candidates if len(m.get('parameters', [])) == param_count]
                    chosen = by_count[0] if by_count else candidates[0]
            else:
                chosen = candidates[0]

            if not chosen:
                continue

            resolved.append({
                'class': class_name,
                'method': method_name,
                'parameters': chosen.get('parameters', parameters),
                'start_line': chosen.get('start_line', 0),
                'end_line': chosen.get('end_line', 0),
                'file': file_rel_path,
                'package': method.get('package', '')
            })

        return resolved
    
    def _extract_compile_error(self, output: str) -> str:
        
        lines = output.split('\n')
        error_lines = []
        
        for line in lines:
            if '[ERROR]' in line or 'error:' in line.lower():
                error_lines.append(line.strip())
        
        if error_lines:
            # detectversioncompatibility issues
            compat_issues = self._detect_compatibility_issues(output)
            error_msg = '\n'.join(error_lines[:10])
            if compat_issues:
                error_msg = f"[COMPATIBILITY ISSUES DETECTED]\n{compat_issues}\n\n{error_msg}"
            return error_msg
        return "Compilation failed"
    
    def _detect_compatibility_issues(self, output: str) -> str:
        """detectversioncompatibility issues"""
        issues = []
        
        # Java version
        if 'Source option' in output and 'is no longer supported' in output:
            issues.append("⚠️  Javaversion: source-only version，JDK")
        if 'Target option' in output and 'is no longer supported' in output:
            issues.append("⚠️  Javaversion: version")
        if 'has been removed' in output.lower() and 'release' in output.lower():
            issues.append("⚠️  Javaversion: Java releaseversion")
        if 'invalid target release' in output.lower():
            issues.append("⚠️  Javaversion: releaseversion")
        if 'class file has wrong version' in output.lower():
            issues.append("⚠️  Javaversion: classfileversionJDK")
        
        # Maven
        if 'Could not find artifact' in output and 'plugin' in output.lower():
            issues.append("⚠️  Maven: get")
        if 'Plugin' in output and 'not found' in output:
            issues.append("⚠️  Maven: projectdoes not exist")
        if 'Unsupported major.minor version' in output:
            issues.append("⚠️  version: versionJava")
        
        if 'Could not resolve dependencies' in output:
            issues.append("⚠️  parseFailed: parseproject")
        if 'Could not find artifact' in output and 'plugin' not in output.lower():
            issues.append("⚠️  : get")
        if 'Repository' in output and ('refused' in output or 'blocked' in output):
            issues.append("⚠️  : MavenHTTPS")
        if 'PKIX path building failed' in output or 'SSL' in output:
            issues.append("⚠️  SSL: SSLvalidatefail")
        if 'Connection refused' in output or 'Connection timed out' in output:
            issues.append("⚠️  : Maven")
        
        if 'Unrecognised tag' in output or 'Malformed POM' in output:
            issues.append("⚠️  POMformat: pom.xmlformatMavenversion")
        if 'Non-parseable POM' in output:
            issues.append("⚠️  POMparseFailed: pom.xmlMavenparse")
        
        if issues:
            return '\n'.join(issues)
        return ""
    
    def _parse_compile_errors(self, output: str) -> list:
        
        errors = []
        lines = output.split('\n')
        
        for i, line in enumerate(lines):
            if '.java:' in line and ('error:' in line.lower() or '[ERROR]' in line):
                try:
                    parts = line.split('.java:')
                    if len(parts) >= 2:
                        file_part = parts[0].split('/')[-1] + '.java'
                        rest = parts[1]
                        
                        line_num = None
                        if ':' in rest:
                            try:
                                line_num = int(rest.split(':')[0].strip().strip('[').strip(']'))
                            except:
                                pass
                        
                        errors.append({
                            'file': file_part,
                            'line': line_num,
                            'message': line.strip()
                        })
                except:
                    pass
        
        return errors[:10]
    
    def _parse_test_summary(self, output: str) -> dict:
        
        result = {
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0
        }
        
        import re
        
        pattern = r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)'
        matches = re.findall(pattern, output)
        
        if matches:
            for match in matches:
                result['total_tests'] += int(match[0])
                result['failed'] += int(match[1])
                result['errors'] += int(match[2])
                result['skipped'] += int(match[3])
            
            result['passed'] = result['total_tests'] - result['failed'] - result['errors'] - result['skipped']
        
        return result
    
    def _parse_failed_tests(self, worktree_path: str) -> list:
        
        failed_tests = []
        
        surefire_dir = os.path.join(worktree_path, 'target', 'surefire-reports')
        
        if os.path.exists(surefire_dir):
            import xml.etree.ElementTree as ET
            
            for filename in os.listdir(surefire_dir):
                if filename.startswith('TEST-') and filename.endswith('.xml'):
                    try:
                        filepath = os.path.join(surefire_dir, filename)
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
                                    'message': elem.get('message', '')[:500],
                                    'stack_trace': (elem.text or '')[:1000]
                                })
                    except Exception as e:
                        logger.debug(f"parsereportfail {filename}: {e}")
        
        return failed_tests[:50]

    def _parse_test_summary_from_reports(self, worktree_path: str) -> Optional[dict]:
        
        surefire_dir = os.path.join(worktree_path, 'target', 'surefire-reports')
        if not os.path.exists(surefire_dir):
            return None

        totals = {
            'total_tests': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': 0
        }
        parsed_any = False

        import xml.etree.ElementTree as ET

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

                totals['total_tests'] += tests
                totals['failed'] += failures
                totals['errors'] += errors
                totals['skipped'] += skipped
                parsed_any = True
            except Exception:
                continue

        if not parsed_any:
            return None

        totals['passed'] = totals['total_tests'] - totals['failed'] - totals['errors'] - totals['skipped']
        return totals

    def _derive_test_status(self, result: Dict[str, Any]) -> tuple:
        
        if result.get('selection_skipped'):
            return 'skip', "No changed tests identified"

        failed = result.get('failed', 0)
        errors = result.get('errors', 0)
        total = result.get('total_tests', 0)
        return_code = result.get('return_code', 0)

        if failed > 0 or errors > 0:
            return 'fail', None

        if total == 0:
            if return_code not in (0, None, -1):
                return 'error', "Test execution failed"
            return 'skip', "No tests run"

        if return_code not in (0, None, -1):
            return 'error', "Test execution failed"

        return 'pass', None

    def _detect_test_compile_error(self, output: str) -> Optional[str]:
        
        if not output:
            return None

        lower = output.lower()
        if 'could not compile test sources' in lower:
            return "Test compilation failed: could not compile test sources"

        if 'failed to execute goal' in lower and ('testcompile' in lower or 'test-compile' in lower):
            for line in output.splitlines():
                line_lower = line.lower()
                if 'failed to execute goal' in line_lower and ('testcompile' in line_lower or 'test-compile' in line_lower):
                    return line.strip()[:200]

        if ('compilation error' in lower or 'compilation failure' in lower) and ('testcompile' in lower or 'test-compile' in lower):
            return "Test compilation failed"

        return None
    
    def _cleanup_worktree(self, worktree_path: str):
        """clean upworktree"""
        try:
            if os.path.exists(worktree_path):
                try:
                    self.repo.git.worktree('remove', '--force', worktree_path)
                except:
                    pass
                
                if os.path.exists(worktree_path):
                    shutil.rmtree(worktree_path, ignore_errors=True)
                
                logger.debug(f"clean upworktree: {worktree_path}")
                
                with self._worktrees_lock:
                    if worktree_path in self._created_worktrees:
                        self._created_worktrees.remove(worktree_path)
                    
        except Exception as e:
            logger.warning(f"clean upworktreefail {worktree_path}: {e}")
    
    def cleanup_all(self):
        
        # clean uprecord
        with self._worktrees_lock:
            worktrees_copy = list(self._created_worktrees)
        for worktree_path in worktrees_copy:
            self._cleanup_worktree(worktree_path)
        
        # clean up
        try:
            # get
            output = self.repo.git.worktree('list', '--porcelain')
            
            for line in output.split('\n'):
                if line.startswith('worktree '):
                    path = line.replace('worktree ', '').strip()
                    if self.work_dir in path and self.project_name in path:
                        self._cleanup_worktree(path)
        except Exception as e:
            logger.debug(f"clean upworktreeFailed: {e}")
        
        # executegit worktree prune
        try:
            self.repo.git.worktree('prune')
        except:
            pass
