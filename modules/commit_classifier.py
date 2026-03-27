"""
Commit classifier - classifies commits into three types based on execution results

Type definitions:
- Type1 (execution error): V-0.5 compilation or test failure
- Type2 (coverage gap): V0 has higher coverage than V-0.5, indicating old tests cover insufficiently
- Type3 (adaptive change): qualified commits that are neither Type1 nor Type2
"""

from typing import Dict, Any

from config import AnalysisConfig
from utils.logger import get_logger

logger = get_logger()


class CommitClassifier:
    """Commit classifier - detects three types of obsolete test cases"""
    
    def __init__(self, coverage_threshold: float = None):
        """
        Initialize classifier
        
        Args:
            coverage_threshold: Coverage decrease threshold, defaults to config value
        """
        if coverage_threshold is None:
            coverage_threshold = AnalysisConfig.COVERAGE_DECREASE_THRESHOLD
        self.coverage_threshold = coverage_threshold
    
    def classify(self,
                 v1_result: Dict[str, Any],
                 v05_result: Dict[str, Any],
                 t05_result: Dict[str, Any],
                 v0_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify a commit
        
        Classification logic:
        1. First detect Type1 (execution error)
        2. Then detect Type2 (coverage gap)
        3. If neither Type1 nor Type2, classify as Type3 (adaptive change)
        
        T-0.5 is used for supplementary analysis to provide additional confidence information
        
        Args:
            v1_result: V-1 version execution result
            v05_result: V-0.5 version execution result
            t05_result: T-0.5 version execution result
            v0_result: V0 version execution result
            
        Returns:
            Classification result dictionary
        """
        # Determine scenario
        scenario = self._determine_scenario(v05_result, t05_result)
        scenario_desc = self._get_scenario_description(scenario)
        
        # Detect Type1
        type1_result = self._detect_type1(v05_result, t05_result, v0_result)

        # Detect Type2
        type2_result = self._detect_type2(v05_result, t05_result, v0_result)

        # Detect Type3 (fallback)
        is_type1 = type1_result.get('detected', False)
        is_type2 = type2_result.get('detected', False)
        type3_result = self._detect_type3(is_type1, is_type2, scenario)
        
        # Summarize
        all_types = []
        if is_type1:
            all_types.append('type1_execution_error')
        if is_type2:
            all_types.append('type2_coverage_decrease')
        if type3_result.get('detected', False):
            all_types.append('type3_adaptive_change')
        
        # Determine primary type (priority: Type1 > Type2 > Type3)
        primary_type = None
        if all_types:
            primary_type = all_types[0]
        
        return {
            'scenario': scenario,
            'scenario_description': scenario_desc,
            'type1_execution_error': type1_result,
            'type2_coverage_decrease': type2_result,
            'type3_adaptive_change': type3_result,
            'all_types': all_types,
            'primary_type': primary_type,
            'types_count': len(all_types)
        }
    
    def _determine_scenario(self, v05_result: Dict, t05_result: Dict) -> str:
        """
        Determine which scenario (A/B/C/D)
        
        Scenario definitions:
        - A: V-0.5 fails, T-0.5 fails
        - B: V-0.5 fails, T-0.5 passes
        - C: V-0.5 passes, T-0.5 fails
        - D: V-0.5 passes, T-0.5 passes
        """
        v05_state = self._get_version_state(v05_result)
        t05_state = self._get_version_state(t05_result)

        if v05_state == 'unknown' or t05_state == 'unknown':
            return 'U'

        v05_pass = v05_state == 'pass'
        t05_pass = t05_state == 'pass'

        if not v05_pass and not t05_pass:
            return 'A'
        elif not v05_pass and t05_pass:
            return 'B'
        elif v05_pass and not t05_pass:
            return 'C'
        else:
            return 'D'
    
    def _is_version_pass(self, result: Dict) -> bool:
        """Check if version passes (build success and test success)"""
        if not result:
            return False
        
        build_success = result.get('build', {}).get('success', False)
        test_status = self._get_test_status(result)
        
        return build_success and test_status == 'pass'

    def _get_version_state(self, result: Dict) -> str:
        """Get version state: pass / fail / unknown"""
        if not result:
            return 'unknown'

        build_success = result.get('build', {}).get('success', False)
        test_status = self._get_test_status(result)

        if not build_success:
            return 'fail'

        if test_status == 'pass':
            return 'pass'
        if test_status == 'fail':
            return 'fail'
        return 'unknown'

    def _get_test_status(self, result: Dict) -> str:
        """Extract test status: pass / fail / skip / error / unknown"""
        test = result.get('test', {}) if result else {}
        status = test.get('status')
        if status:
            return status
        success = test.get('success')
        if success is True:
            return 'pass'
        if success is False:
            return 'fail'
        return 'unknown'
    
    def _get_scenario_description(self, scenario: str) -> str:
        """Get scenario description"""
        descriptions = {
            'A': 'V-0.5 fails, T-0.5 fails: source code behavior changed, neither old nor new tests adapt',
            'B': 'V-0.5 fails, T-0.5 passes: old tests fail, but new tests work on old code',
            'C': 'V-0.5 passes, T-0.5 fails: old tests pass, new tests cover newly introduced functionality',
            'D': 'V-0.5 passes, T-0.5 passes: minor adjustment, possibly coverage change or adaptive modification',
            'U': 'V-0.5 or T-0.5 tests skipped/result unknown: scenario uncertain'
        }
        return descriptions.get(scenario, 'Unknown scenario')
    
    def _detect_type1(self, v05_result: Dict, t05_result: Dict, v0_result: Dict) -> Dict:
        """
        Detect Type1: execution error
        
        Detection criteria:
        - V-0.5 compile failure → Type1a (compile_failure)
        - V-0.5 test failure and V0 test passes → Type1b (runtime_failure)
        
        T-0.5 supplementary analysis:
        - If T-0.5 also fails (scenario A), confidence is higher
        - If T-0.5 passes (scenario B), may involve test refactoring
        """
        result = {
            'detected': False,
            'subtype': None,
            'confidence': None,
            'evidence': {}
        }
        
        v05_build = v05_result.get('build', {})
        v05_test = v05_result.get('test', {})
        v0_test = v0_result.get('test', {})
        t05_build = t05_result.get('build', {})
        t05_test = t05_result.get('test', {})
        
        # Case 1: V-0.5 compilation failure
        if not v05_build.get('success', False):
            result['detected'] = True
            result['subtype'] = 'compile_failure'
            result['confidence'] = 'high'
            result['evidence'] = {
                'v05_build_success': False,
                'error_message': v05_build.get('error_message'),
                'compile_errors': v05_build.get('compile_errors', []),
                't05_build_success': t05_build.get('success', False)
            }
            return result
        
        # Case 2: V-0.5 test compilation failure
        v05_test_status = self._get_test_status(v05_result)
        v0_test_status = self._get_test_status(v0_result)
        v05_error_type = v05_test.get('error_type')

        if v05_test_status == 'error' and v05_error_type == 'test_compile':
            result['detected'] = True
            result['subtype'] = 'test_compile_failure'
            result['confidence'] = 'high'
            result['evidence'] = {
                'v05_test_status': v05_test_status,
                'v05_error_type': v05_error_type,
                'error_message': v05_test.get('error_message'),
                't05_test_status': self._get_test_status(t05_result),
                'v0_test_status': v0_test_status
            }
            return result

        # Case 3: V-0.5 test failure
        if v05_test_status == 'fail':
            # Confirm V0 tests pass (rule out pre-existing test issues)
            if v0_test_status == 'pass':
                result['detected'] = True
                result['subtype'] = 'runtime_failure'
                
                # Adjust confidence based on T-0.5 result
                t05_test_status = self._get_test_status(t05_result)
                
                if t05_test_status == 'fail':
                    # Scenario A: T-0.5 also fails, high confidence
                    result['confidence'] = 'high'
                    result['evidence']['t05_analysis'] = 'T-0.5 also fails, confirms source code behavior change'
                elif t05_test_status == 'pass':
                    # Scenario B: T-0.5 passes, medium confidence
                    result['confidence'] = 'medium'
                    result['evidence']['t05_analysis'] = 'T-0.5 passes, new tests work on old code, may involve test refactoring'
                else:
                    result['confidence'] = 'low'
                    result['evidence']['t05_analysis'] = 'T-0.5 tests skipped or result unknown, confidence reduced'
                
                result['evidence']['v05_test_status'] = v05_test_status
                result['evidence']['v0_test_status'] = v0_test_status
                result['evidence']['failed_tests_count'] = v05_test.get('failed', 0) + v05_test.get('errors', 0)
                result['evidence']['failed_tests'] = v05_test.get('failed_tests', [])[:10]
        elif v05_test_status in ('skip', 'error', 'unknown'):
            result['evidence']['note'] = f"V-0.5 test status is {v05_test_status}, cannot determine Type1 runtime failure"
        
        return result
    
    def _detect_type2(self, v05_result: Dict, t05_result: Dict, v0_result: Dict) -> Dict:
        """
        Detect Type2: coverage gap
        
        Detection criteria:
        - V0 has higher changed-method coverage than V-0.5, exceeding threshold
        - Or V0 has higher changed-method branch coverage than V-0.5, exceeding threshold
        
        T-0.5 supplementary analysis:
        - T-0.5 changed-method coverage shows how much coverage new tests add
        """
        result = {
            'detected': False,
            'confidence': None,
            'evidence': {}
        }
        
        # If V-0.5 build fails or tests do not pass, coverage analysis is not accurate
        if not v05_result.get('build', {}).get('success', False):
            result['evidence']['note'] = 'V-0.5 build failed, cannot analyze coverage'
            return result
        v05_test_status = self._get_test_status(v05_result)
        if v05_test_status != 'pass':
            result['evidence']['note'] = f'V-0.5 test status is {v05_test_status}，, cannot analyze coverage'
            return result
        
        # Get coverage data
        v05_coverage = v05_result.get('coverage', {})
        v0_coverage = v0_result.get('coverage', {})
        t05_coverage = t05_result.get('coverage', {}) if t05_result.get('build', {}).get('success') else {}

        # Use line coverage of changed methods (stricter)
        v05_method_cov = v05_coverage.get('method_line_coverage')
        v0_method_cov = v0_coverage.get('method_line_coverage')
        t05_method_cov = t05_coverage.get('method_line_coverage') if t05_coverage else None

        line_signal = None
        branch_signal = None

        if v05_method_cov and v0_method_cov and v05_method_cov.get('total_lines', 0) > 0:
            v05_ratio = v05_method_cov.get('coverage_ratio', 0)
            v0_ratio = v0_method_cov.get('coverage_ratio', 0)
            coverage_diff = v0_ratio - v05_ratio

            if coverage_diff >= self.coverage_threshold:
                line_signal = {
                    'metric': 'changed_methods_line_coverage',
                    'v05_coverage_ratio': round(v05_ratio, 4),
                    'v0_coverage_ratio': round(v0_ratio, 4),
                    'coverage_diff': round(coverage_diff, 4),
                    'total_lines': v05_method_cov.get('total_lines', 0),
                    'threshold': self.coverage_threshold
                }

                if t05_method_cov and t05_method_cov.get('total_lines', 0) > 0:
                    t05_ratio = t05_method_cov.get('coverage_ratio', 0)
                    line_signal['t05_coverage_ratio'] = round(t05_ratio, 4)

        # Branch coverage signal
        branch_threshold = getattr(AnalysisConfig, 'BRANCH_COVERAGE_INCREASE_THRESHOLD', self.coverage_threshold)
        v05_branch_cov = v05_coverage.get('method_branch_coverage')
        v0_branch_cov = v0_coverage.get('method_branch_coverage')
        if v05_branch_cov and v0_branch_cov and v05_branch_cov.get('total_branches', 0) > 0:
            v05_branch_ratio = v05_branch_cov.get('coverage_ratio', 0)
            v0_branch_ratio = v0_branch_cov.get('coverage_ratio', 0)
            branch_diff = v0_branch_ratio - v05_branch_ratio

            if branch_diff >= branch_threshold:
                branch_signal = {
                    'metric': 'changed_methods_branch_coverage',
                    'v05_branch_ratio': round(v05_branch_ratio, 4),
                    'v0_branch_ratio': round(v0_branch_ratio, 4),
                    'branch_coverage_diff': round(branch_diff, 4),
                    'total_branches': v05_branch_cov.get('total_branches', 0),
                    'threshold': branch_threshold
                }

        if line_signal or branch_signal:
            result['detected'] = True
            max_diff = 0.0
            if line_signal:
                max_diff = max(max_diff, line_signal.get('coverage_diff', 0))
            if branch_signal:
                max_diff = max(max_diff, branch_signal.get('branch_coverage_diff', 0))
            result['confidence'] = 'high' if max_diff >= 0.1 else 'medium'
            result['evidence'] = {'signals': []}
            if line_signal:
                result['evidence']['signals'].append(line_signal)
            if branch_signal:
                result['evidence']['signals'].append(branch_signal)

            primary_signal = line_signal or branch_signal
            if primary_signal:
                result['evidence'].update(primary_signal)
            if branch_signal and 'branch_coverage_diff' not in result['evidence']:
                result['evidence']['branch_coverage_diff'] = branch_signal.get('branch_coverage_diff')
            return result

        # Coverage unavailable or no significant increase
        if not (v05_method_cov and v0_method_cov):
            result['evidence']['note'] = 'Changed-method coverage unavailable'
        else:
            result['evidence']['note'] = 'Changed-method coverage increase is not significant'
        
        return result
    
    def _detect_type3(self, is_type1: bool, is_type2: bool, scenario: str) -> Dict:
        """
        Detect Type3: adaptive change
        
        Detection logic:
        - Qualified commits that are neither Type1 nor Type2
        - This is a fallback classification
        """
        result = {
            'detected': False,
            'confidence': None,
            'evidence': {}
        }
        
        # Only commits that are neither Type1 nor Type2 are classified as Type3
        if not is_type1 and not is_type2:
            result['detected'] = True
            result['confidence'] = 'low' if scenario == 'U' else 'high'
            result['evidence'] = {
                'reason': 'Neither Type1 (execution error) nor Type2 (coverage gap), classified as adaptive change',
                'scenario': scenario,
                'scenario_meaning': self._get_type3_scenario_meaning(scenario)
            }
            if scenario == 'U':
                result['evidence']['note'] = 'V-0.5 or T-0.5 tests skipped/result unknown, confidence reduced'
        
        return result
    
    def _get_type3_scenario_meaning(self, scenario: str) -> str:
        """Get the meaning of Type3 under different scenarios"""
        meanings = {
            'C': 'New tests cover newly introduced functionality, old tests still pass',
            'D': 'Minor adaptive adjustment, both old and new tests pass',
            'U': 'Insufficient execution information, scenario uncertain'
        }
        return meanings.get(scenario, 'adaptive change')
