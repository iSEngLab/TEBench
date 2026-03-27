"""
Maven execution module - responsible for Maven builds, test execution, and JaCoCo integration
"""

import os
import subprocess
from config import Config, AnalysisConfig
from utils.logger import get_logger
from utils.pom_modifier import PomModifier

logger = get_logger()


class MavenExecutor:
    """Maven executor"""

    def __init__(self, project_path):
        """
        Initialize the Maven executor

        Args:
            project_path: Maven project path
        """
        self.project_path = project_path
        self.pom_path = os.path.join(project_path, 'pom.xml')

    def has_pom(self):
        """Check whether pom.xml exists"""
        return os.path.exists(self.pom_path)

    def clean(self):
        """Execute Maven clean"""
        return self._run_maven_command('clean')

    def compile(self):
        """Execute Maven compile"""
        return self._run_maven_command('compile')

    def test(self):
        """Execute Maven test"""
        return self._run_maven_command('test')
    
    def test_with_jacoco(self, selected_tests=None):
        """
        Execute tests using JaCoCo

        Args:
            selected_tests: run only the specified tests (list or comma-separated string)

        Returns:
            dict: {'success': bool, 'output': str, 'jacoco_report': str}
        """
        result = {
            'success': False,
            'output': '',
            'jacoco_report': None,
            'stdout': '',
            'stderr': '',
            'return_code': -1
        }

        # Modify pom.xml to add JaCoCo
        pom_modifier = PomModifier(self.pom_path)

        try:
            # Back up and modify the POM
            if not pom_modifier.backup():
                logger.error("Unable to back up pom.xml")
                return result

            if not pom_modifier.add_jacoco_plugin():
                logger.error("Unable to add JaCoCo plugin")
                pom_modifier.restore()
                return result

            # Execute clean test
            extra_args = []
            if selected_tests:
                if isinstance(selected_tests, (list, tuple)):
                    test_value = ",".join([t for t in selected_tests if t])
                else:
                    test_value = str(selected_tests)
                if test_value:
                    extra_args.append(f"-Dtest={test_value}")

            success, output = self._run_maven_command('clean test', extra_args=extra_args)
            result['success'] = success
            result['output'] = output
            result['stdout'] = output
            result['return_code'] = 0 if success else 1

            # Get the JaCoCo report path
            if success:
                jacoco_report_path = os.path.join(self.project_path, Config.JACOCO_REPORT_PATH)
                if os.path.exists(jacoco_report_path):
                    result['jacoco_report'] = jacoco_report_path
                    logger.debug(f"JaCoCo report generated: {jacoco_report_path}")
                else:
                    logger.warning(f"JaCoCo report not found: {jacoco_report_path}")

        except Exception as e:
            logger.error(f"Failed to execute Maven tests: {e}")

        finally:
            # Restore the original POM
            pom_modifier.restore()

        return result
    
    def _run_maven_command(self, goal, extra_args=None):
        """
        Execute a Maven command

        Args:
            goal: Maven goal (e.g. clean, test, compile)

        Returns:
            tuple: (success: bool, output: str)
        """
        try:
            # Use the configured Maven executable
            maven_cmd = AnalysisConfig.MAVEN_EXECUTABLE or Config.MAVEN_CMD

            # Add Maven options to skip RAT check (license validation fails after POM modification)
            # and ignore test failures to allow processing to continue
            cmd = [maven_cmd, '-Drat.skip=true', '-Dmaven.test.failure.ignore=true']

            # Add extra compatibility arguments
            if AnalysisConfig.MAVEN_EXTRA_ARGS:
                cmd += AnalysisConfig.MAVEN_EXTRA_ARGS.split()

            if extra_args:
                cmd += list(extra_args)
            cmd += goal.split()

            logger.debug(f"Executing Maven command: {' '.join(cmd)} @ {self.project_path}")

            # Build environment variables
            env = os.environ.copy()
            if AnalysisConfig.JAVA_HOME:
                env['JAVA_HOME'] = AnalysisConfig.JAVA_HOME
                env['PATH'] = f"{AnalysisConfig.JAVA_HOME}/bin:{env.get('PATH', '')}"

            process = subprocess.Popen(
                cmd,
                cwd=self.project_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env
            )

            # Set timeout
            try:
                output, _ = process.communicate(timeout=Config.MAVEN_TIMEOUT)
                success = process.returncode == 0

                if success:
                    logger.debug(f"Maven command executed successfully: {goal}")
                else:
                    logger.warning(f"Maven command failed (return code: {process.returncode}): {goal}")
                    # Log last part of output for debugging
                    logger.warning(f"Maven output (last 3000 characters): {output[-3000:]}")

                return success, output

            except subprocess.TimeoutExpired:
                process.kill()
                logger.error(f"Maven command timed out: {goal}")
                return False, "Timeout"

        except Exception as e:
            logger.error(f"Maven command execution exception [{goal}]: {e}")
            return False, str(e)
    
    def get_test_failures(self, test_output):
        """
        Extract failed test cases from test output

        Args:
            test_output: output of the Maven test command

        Returns:
            list: list of failed test cases
        """
        failures = []

        try:
            lines = test_output.split('\n')
            for line in lines:
                if 'FAILED' in line or 'ERROR' in line:
                    failures.append(line.strip())

        except Exception as e:
            logger.debug(f"Exception while parsing test failure information: {e}")

        return failures

    def check_compilation(self):
        """
        Check whether the project can be compiled

        Returns:
            bool: whether compilation succeeded
        """
        success, _ = self._run_maven_command('clean compile')
        return success
