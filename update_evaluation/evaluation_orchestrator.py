"""
Evaluation orchestrator - coordinates the entire evaluation pipeline
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from git import Repo

from config import AnalysisConfig
from utils.logger import get_logger
from .worktree_manager import WorktreeManager
from .changed_method_extractor import ChangedMethodExtractor
from .executability_evaluator import ExecutabilityEvaluator
from .coverage_increment_analyzer import CoverageIncrementAnalyzer
from .modification_effort_calculator import ModificationEffortCalculator

logger = get_logger()


class EvaluationOrchestrator:
    """Evaluation orchestrator - coordinates the entire evaluation pipeline"""

    def __init__(self, repo_path: str, cache_dir: str = None):
        """
        Initialize the evaluation orchestrator

        Args:
            repo_path: repository path
            cache_dir: cache directory (for reading analysis results)
        """
        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        self.repo = Repo(repo_path)
        self.cache_dir = cache_dir or AnalysisConfig.CACHE_DIR

        # Initialize components
        self.worktree_manager = WorktreeManager(repo_path)
        self.method_extractor = ChangedMethodExtractor(repo_path)
        self.executability_evaluator = ExecutabilityEvaluator()
        self.coverage_analyzer = CoverageIncrementAnalyzer()
        self.effort_calculator = ModificationEffortCalculator(repo_path)

    def prepare_evaluation(self, gt_commit: str) -> Dict[str, Any]:
        """
        Prepare the evaluation environment

        Args:
            gt_commit: GT commit hash

        Returns:
            dict: preparation result
        """
        return self.worktree_manager.prepare_evaluation_worktree(
            gt_commit, self.cache_dir
        )

    def run_evaluation(self, worktree_path: str, gt_commit: str) -> Dict[str, Any]:
        """
        Run evaluation (read-only operation, does not modify git state)

        Args:
            worktree_path: worktree path after user modifications
            gt_commit: GT commit hash

        Returns:
            dict: evaluation results
        """
        result = {
            'success': False,
            'project': self.project_name,
            'gt_commit': gt_commit,
            'evaluation': {
                'executability': {},
                'coverage_analysis': {},
                'coverage_overlap': {},
                'modification_effort': {}
            },
            'error': None,
            'timestamp': datetime.now().isoformat()
        }

        try:
            # 1. Get worktree info (parsed from git)
            metadata = self.worktree_manager.get_worktree_info(worktree_path)
            if not metadata:
                result['error'] = "Failed to retrieve worktree info"
                return result

            v05_commit = metadata.get('v05_commit')
            result['v05_commit'] = v05_commit
            result['task_id'] = metadata.get('task_id')

            # 2. Analyze user modifications (analyze only, do not commit)
            user_changes = self._analyze_user_changes(worktree_path, v05_commit, gt_commit)
            result['user_changes'] = user_changes

            if not user_changes.get('has_changes'):
                result['error'] = "No modifications detected"
                return result

            # 3. Executability evaluation
            logger.info("Running executability evaluation...")

            # Compute the union of test methods modified by User and GT
            user_test_methods = user_changes.get('test_methods', [])
            gt_test_methods = user_changes.get('gt_test_methods', [])
            all_test_methods = self._merge_test_methods(user_test_methods, gt_test_methods)

            logger.debug(f"User modified test methods: {len(user_test_methods)}, GT modified test methods: {len(gt_test_methods)}, union: {len(all_test_methods)}")

            executability = self.executability_evaluator.evaluate(
                worktree_path,
                all_test_methods  # use the union
            )
            result['evaluation']['executability'] = executability

            # If compilation fails, skip subsequent evaluations
            if not executability.get('compile_success'):
                result['error'] = "Compilation failed; skipping coverage and modification effort evaluation"
                return result

            # 4. Coverage analysis (supports two modes)
            logger.info("Running coverage analysis...")
            source_methods = user_changes.get('gt_source_methods', [])

            # Coverage evaluation mode switch:
            # - 'increment': original coverage increment logic (V-0.5 / User / GT three versions)
            # - 'direct': new logic (only run User and GT changed tests, compare coverage of changed source methods)
            coverage_mode = 'direct'

            coverage_result = self._analyze_coverage_with_worktrees(
                v05_commit,
                gt_commit,
                worktree_path,
                source_methods,
                all_test_methods,
                mode=coverage_mode
            )
            # New field (recommended)
            result['evaluation']['coverage_analysis'] = coverage_result
            # Backward-compatible field (to avoid breaking external scripts)
            result['evaluation']['coverage_overlap'] = coverage_result
            result['coverage_mode'] = coverage_mode

            # 5. Modification effort calculation (supports two modes)
            logger.info("Calculating modification effort...")
            effort_result = self._calculate_modification_effort(
                worktree_path,
                gt_commit,
                v05_commit,
                all_test_methods,
                metric='direction'  # currently using minimum-effort mode; change to metric='direction' for directional consistency evaluation
            )
            result['evaluation']['modification_effort'] = effort_result

            # 6. Calculate composite score
            result['scores'] = self._calculate_scores(result['evaluation'])

            result['success'] = True

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            result['error'] = str(e)

        return result

    def _analyze_user_changes(self, worktree_path: str, v05_commit: str, gt_commit: str) -> Dict[str, Any]:
        """
        Analyze user modifications (analyze working tree changes without committing)

        Returns:
            dict: {
                'has_changes': bool,
                'changed_files': list,
                'test_methods': list,  # test methods modified by user
                'gt_source_methods': list,  # source code methods changed in GT
                'common_methods': list  # test methods modified by both user and GT
            }
        """
        from git import Repo

        result = {
            'has_changes': False,
            'changed_files': [],
            'test_methods': [],
            'gt_source_methods': [],
            'common_methods': []
        }

        try:
            worktree_repo = Repo(worktree_path)

            # Check for modifications (staged + unstaged + untracked)
            changed_files = []

            # staged changes
            for item in worktree_repo.index.diff('HEAD'):
                changed_files.append(item.a_path or item.b_path)

            # unstaged changes
            for item in worktree_repo.index.diff(None):
                if item.a_path not in changed_files:
                    changed_files.append(item.a_path)

            # untracked files
            for f in worktree_repo.untracked_files:
                if f not in changed_files:
                    changed_files.append(f)

            result['changed_files'] = changed_files
            result['has_changes'] = len(changed_files) > 0

            if not result['has_changes']:
                return result

            # Extract test methods modified by the user (from working tree analysis)
            user_test_methods = self._extract_user_test_methods(worktree_path, v05_commit)
            result['test_methods'] = user_test_methods

            # Extract GT source and test methods
            # Note: source code changes should be relative to V-0.5's parent (i.e., the original version),
            # not V-0.5 itself, because V-0.5 already includes the source code changes
            v05_parent = self.repo.commit(v05_commit).parents[0].hexsha if self.repo.commit(v05_commit).parents else v05_commit
            gt_source_methods = self.method_extractor._extract_changed_source_methods(gt_commit, v05_parent)
            gt_test_methods = self.method_extractor._extract_changed_test_methods(gt_commit, v05_commit)
            result['gt_source_methods'] = gt_source_methods
            result['gt_test_methods'] = gt_test_methods  # save GT test methods for executability evaluation

            logger.debug(f"GT source code changed methods: {len(gt_source_methods)} (relative to {v05_parent[:8]})")
            for m in gt_source_methods:
                logger.debug(f"  - {m.get('class')}.{m.get('method')} ({m.get('file')}:{m.get('start_line')}-{m.get('end_line')})")

            # Compute commonly modified test methods
            user_keys = {(m.get('file'), m.get('class'), m.get('method')) for m in user_test_methods}
            gt_keys = {(m.get('file'), m.get('class'), m.get('method')) for m in gt_test_methods}
            common_keys = user_keys & gt_keys

            # Build common_methods with line number info from both sides
            user_methods_map = {(m.get('file'), m.get('class'), m.get('method')): m for m in user_test_methods}
            gt_methods_map = {(m.get('file'), m.get('class'), m.get('method')): m for m in gt_test_methods}

            for key in common_keys:
                user_m = user_methods_map.get(key)
                gt_m = gt_methods_map.get(key)
                if user_m and gt_m:
                    result['common_methods'].append({
                        'file': key[0],
                        'class': key[1],
                        'method': key[2],
                        'package': user_m.get('package', ''),
                        'user_start_line': user_m.get('start_line'),
                        'user_end_line': user_m.get('end_line'),
                        'gt_start_line': gt_m.get('start_line'),
                        'gt_end_line': gt_m.get('end_line')
                    })

            logger.debug(f"User modifications: {len(changed_files)} files, {len(user_test_methods)} test methods, "
                        f"{len(result['common_methods'])} common methods")

        except Exception as e:
            logger.error(f"Failed to analyze user modifications: {e}")

        return result

    def _merge_test_methods(self, user_methods: List[Dict], gt_methods: List[Dict]) -> List[Dict]:
        """
        Merge test methods modified by User and GT (union)

        Args:
            user_methods: test methods modified by User
            gt_methods: test methods modified by GT

        Returns:
            list: merged (deduplicated) list of test methods
        """
        merged = {}

        # Add User methods
        for m in user_methods:
            key = (m.get('file'), m.get('class'), m.get('method'))
            merged[key] = m

        # Add GT methods (if not already present)
        for m in gt_methods:
            key = (m.get('file'), m.get('class'), m.get('method'))
            if key not in merged:
                merged[key] = m

        return list(merged.values())

    def _extract_user_test_methods(self, worktree_path: str, v05_commit: str) -> List[Dict]:
        """
        Extract test methods modified by the user from the worktree's working tree
        """
        from git import Repo
        from modules.code_analyzer import CodeAnalyzer
        from modules.change_detector import ChangeDetector
        from config import Config

        methods = []
        code_analyzer = CodeAnalyzer()
        change_detector = ChangeDetector()

        try:
            worktree_repo = Repo(worktree_path)

            # Get diff relative to HEAD (includes staged and unstaged)
            diff_text = worktree_repo.git.diff('HEAD')

            if not diff_text:
                return methods

            # Parse diff
            parsed = change_detector.parse_diff(diff_text)

            for entry in parsed:
                file_path = entry.get('file')
                if not file_path or not file_path.endswith('.java'):
                    continue

                # Only process test files
                if not any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS):
                    continue

                # Read the current file content from the working tree
                full_path = os.path.join(worktree_path, file_path)
                if not os.path.exists(full_path):
                    continue

                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Parse methods
                classes_info = code_analyzer.parse_java_file(content)
                package = code_analyzer.get_package_name(content)

                all_methods = []
                for cls in classes_info.get('classes', []):
                    for m in cls.get('methods', []):
                        all_methods.append({
                            'class': cls.get('name'),
                            'method': m.get('name'),
                            'parameters': m.get('parameters', []),
                            'start_line': m.get('start_line', 0),
                            'end_line': m.get('end_line', 0),
                            'package': package,
                            'file': file_path
                        })

                # Identify changed methods
                for change in entry.get('changes', []):
                    for line_no in change.get('added_lines', []):
                        for m in all_methods:
                            if m['start_line'] <= line_no <= m['end_line']:
                                key = (m['file'], m['class'], m['method'])
                                if not any((em['file'], em['class'], em['method']) == key for em in methods):
                                    methods.append(m)
                                break

            # Resolve data provider methods (@MethodSource referenced methods) -> replace with actual parameterized test methods
            content_map = {}
            for m in methods:
                fp = m.get('file', '')
                if fp and fp not in content_map:
                    full_path = os.path.join(worktree_path, fp)
                    if os.path.exists(full_path):
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f_:
                            content_map[fp] = f_.read()
            methods = self.method_extractor._resolve_data_providers(methods, content_map)

        except Exception as e:
            logger.debug(f"Failed to extract user test methods: {e}")

        return methods

    def _find_method_in_commit(self, commit_hash: str, file_path: str,
                               class_name: str, method_name: str) -> Optional[Dict]:
        """
        Find a method by name in a specified commit (returns correct line numbers in that commit)

        Args:
            commit_hash: commit hash
            file_path: file path
            class_name: class name
            method_name: method name

        Returns:
            dict: method info (with correct line numbers), or None if not found
        """
        try:
            content = self.method_extractor._get_file_content(commit_hash, file_path)
            if not content:
                return None

            all_methods = self.method_extractor._extract_all_methods(content, file_path)
            for m in all_methods:
                if m.get('class') == class_name and m.get('method') == method_name:
                    return m
            return None
        except Exception as e:
            logger.debug(f"Failed to find method {class_name}.{method_name} in commit {commit_hash[:8]}: {e}")
            return None

    def _find_method_in_worktree(self, worktree_path: str, file_path: str,
                                  class_name: str, method_name: str) -> Optional[Dict]:
        """
        Find a method by name in the worktree filesystem (returns correct line numbers)

        Args:
            worktree_path: worktree path
            file_path: relative file path
            class_name: class name
            method_name: method name

        Returns:
            dict: method info (with correct line numbers), or None if not found
        """
        try:
            full_path = os.path.join(worktree_path, file_path)
            if not os.path.exists(full_path):
                return None

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            all_methods = self.method_extractor._extract_all_methods(content, file_path)
            for m in all_methods:
                if m.get('class') == class_name and m.get('method') == method_name:
                    return m
            return None
        except Exception as e:
            logger.debug(f"Failed to find method {class_name}.{method_name} in worktree: {e}")
            return None

    def _calculate_modification_effort(self,
                                        worktree_path: str,
                                        gt_commit: str,
                                        v05_commit: str,
                                        all_test_methods: List[Dict],
                                        metric: str = 'direction') -> Dict[str, Any]:
        """
        Calculate modification effort score (supports two evaluation modes)

        Computed based on the union of User+GT test methods.
        For each method, look it up by name in the worktree (User version) and in the target
        baseline commit, then compute the token Jaccard similarity.

        metric='direction':
            direction_score = Jaccard(User_tokens, GT_tokens)
            Higher score means closer to GT.

        metric='effort':
            effort_score = Jaccard(V05_tokens, User_tokens)
            Higher score means fewer changes (closer to V-0.5).

        Note: always returns average_score for _calculate_scores to read.
        """
        if metric not in ('direction', 'effort'):
            logger.warning(f"Unknown modification effort evaluation mode: {metric}, falling back to direction")
            metric = 'direction'

        result = {
            'method_details': [],
            'metric': metric,
            'average_score': 0.0,
            'direction_score': 0.0,
            'effort_score': 0.0,
            'total_methods': len(all_test_methods),
            'error': None
        }

        if not all_test_methods:
            # When the method set is empty, treat both direction and effort as 0.0
            result['average_score'] = 0.0
            return result

        try:
            score_sum = 0.0
            valid_count = 0

            for method in all_test_methods:
                file_path = method.get('file')
                class_name = method.get('class')
                method_name = method.get('method')

                # Find the user version of the method by name in the worktree
                user_method = self._find_method_in_worktree(
                    worktree_path, file_path, class_name, method_name
                )
                if user_method:
                    full_path = os.path.join(worktree_path, file_path)
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    lines = content.split('\n')
                    start = user_method.get('start_line', 0)
                    end = user_method.get('end_line', 0)
                    if start > 0 and end > 0 and end <= len(lines):
                        user_code = '\n'.join(lines[start-1:end])
                    else:
                        user_code = ""
                else:
                    user_code = ""

                # Select baseline code based on evaluation mode
                user_tokens = self.effort_calculator._tokenize(user_code) if user_code else []
                gt_tokens = []
                v05_tokens = []

                if metric == 'direction':
                    gt_method = self._find_method_in_commit(
                        gt_commit, file_path, class_name, method_name
                    )
                    if gt_method:
                        gt_code = self.effort_calculator._extract_method_code(
                            gt_commit, file_path,
                            gt_method.get('start_line'),
                            gt_method.get('end_line')
                        ) or ""
                    else:
                        gt_code = ""

                    gt_tokens = self.effort_calculator._tokenize(gt_code) if gt_code else []
                    score = self.effort_calculator._jaccard_similarity(user_tokens, gt_tokens)

                    logger.debug(f"Direction score calculation - {class_name}.{method_name}: {score:.4f}")
                else:
                    v05_method = self._find_method_in_commit(
                        v05_commit, file_path, class_name, method_name
                    )
                    if v05_method:
                        v05_code = self.effort_calculator._extract_method_code(
                            v05_commit, file_path,
                            v05_method.get('start_line'),
                            v05_method.get('end_line')
                        ) or ""
                    else:
                        v05_code = ""

                    v05_tokens = self.effort_calculator._tokenize(v05_code) if v05_code else []
                    score = self.effort_calculator._jaccard_similarity(v05_tokens, user_tokens)

                    logger.debug(f"Effort score calculation - {class_name}.{method_name}: {score:.4f}")

                result['method_details'].append({
                    'class': class_name,
                    'method': method_name,
                    'file': file_path,
                    'metric': metric,
                    'v05_tokens': len(v05_tokens),
                    'gt_tokens': len(gt_tokens),
                    'user_tokens': len(user_tokens),
                    'in_user': user_method is not None,
                    'score': score
                })

                score_sum += score
                valid_count += 1

            if valid_count > 0:
                result['average_score'] = score_sum / valid_count

            # Backward-compatible output: sync to corresponding field based on current mode
            if metric == 'direction':
                result['direction_score'] = result['average_score']
            else:
                result['effort_score'] = result['average_score']

        except Exception as e:
            logger.error(f"Failed to calculate modification effort score: {e}")
            result['error'] = str(e)

        return result

    def _calculate_scores(self, evaluation: Dict) -> Dict[str, float]:
        """
        Calculate composite score

        Formula:
        - If not executable: score = 0
        - If GT has no coverage increment: score = modification effort score (coverage not counted)
        - Otherwise: score = 0.6 x coverage overlap + 0.4 x modification effort score
        """
        scores = {
            'executability': 0.0,
            'coverage_overlap': 0.0,
            'modification_score': 0.0,
            'overall': 0.0
        }

        # Executability (threshold condition)
        exec_eval = evaluation.get('executability', {})
        if exec_eval.get('compile_success'):
            scores['executability'] = 0.5
            if exec_eval.get('test_success'):
                scores['executability'] = 1.0

        # Coverage score (read new field first, fall back to old field)
        cov_eval = evaluation.get('coverage_analysis') or evaluation.get('coverage_overlap', {})
        line_overlap = cov_eval.get('line_overlap_ratio', 0)
        branch_overlap = cov_eval.get('branch_overlap_ratio', 0)
        gt_line_count = cov_eval.get('gt_increment_lines', 0)
        gt_branch_count = cov_eval.get('gt_increment_branches', 0)

        overlap_values = []
        if gt_line_count > 0:
            overlap_values.append(line_overlap)
        if gt_branch_count > 0:
            overlap_values.append(branch_overlap)

        if overlap_values:
            scores['coverage_overlap'] = sum(overlap_values) / len(overlap_values)
        else:
            scores['coverage_overlap'] = 0.0

        # Modification effort score (Jaccard(V05, User), higher is better)
        effort_eval = evaluation.get('modification_effort', {})
        scores['modification_score'] = effort_eval.get('average_score', 0)

        # Whether GT has a coverage increment
        gt_has_increment = cov_eval.get('gt_has_increment', True)

        # Composite score
        # If not executable, score is 0
        if scores['executability'] < 1.0:
            scores['overall'] = 0.0
        elif not gt_has_increment:
            # GT has no coverage increment, use only modification effort for composite score
            scores['overall'] = scores['modification_score']
            logger.debug("GT has no coverage increment; composite score uses modification effort score only")
        else:
            scores['overall'] = (
                0.6 * scores['coverage_overlap'] +
                0.4 * scores['modification_score']
            )

        return scores

    def _analyze_coverage_with_worktrees(self,
                                         v05_commit: str,
                                         gt_commit: str,
                                         user_worktree: str,
                                         source_methods: List[Dict],
                                         test_methods: List[Dict] = None,
                                         mode: str = 'increment') -> Dict[str, Any]:
        """
        Coverage analysis dispatch entry point.

        Args:
            mode:
                - 'increment': use coverage increment analysis (V-0.5 / User / GT)
                - 'direct': use GT baseline direct comparison (User / GT only)
        """
        if mode == 'direct':
            return self._analyze_coverage_direct_with_worktrees(
                gt_commit, user_worktree, source_methods, test_methods
            )
        return self._analyze_coverage_increment_with_worktrees(
            v05_commit, gt_commit, user_worktree, source_methods, test_methods
        )

    def _analyze_coverage_increment_with_worktrees(self,
                                                   v05_commit: str,
                                                   gt_commit: str,
                                                   user_worktree: str,
                                                   source_methods: List[Dict],
                                                   test_methods: List[Dict] = None) -> Dict[str, Any]:
        """Run coverage increment analysis using temporary worktrees (legacy logic)."""
        result = {
            'mode': 'increment',
            'line_overlap_ratio': 0.0,
            'branch_overlap_ratio': 0.0,
            'gt_increment_lines': 0,
            'gt_increment_branches': 0,
            'user_increment_lines': 0,
            'common_increment_lines': 0,
            'gt_has_increment': False,
            'error': None
        }

        v05_worktree = None
        gt_worktree = None

        try:
            # Create V-0.5 worktree (directly from v05_commit, no patch needed)
            v05_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_v05_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', v05_worktree, v05_commit)

            # Create GT worktree
            gt_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_gt_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', gt_worktree, gt_commit)

            # Analyze coverage increment
            coverage_result = self.coverage_analyzer.analyze(
                v05_worktree, user_worktree, gt_worktree, source_methods, test_methods
            )

            result['line_overlap_ratio'] = coverage_result['overlap_ratio']['line']
            result['branch_overlap_ratio'] = coverage_result['overlap_ratio']['branch']
            result['gt_increment_lines'] = len(coverage_result['gt_increment']['lines'])
            result['gt_increment_branches'] = len(coverage_result['gt_increment']['branches'])
            result['user_increment_lines'] = len(coverage_result['user_increment']['lines'])
            result['common_increment_lines'] = len(
                coverage_result['gt_increment']['lines'] &
                coverage_result['user_increment']['lines']
            )
            result['gt_has_increment'] = coverage_result.get('gt_has_increment', False)

        except Exception as e:
            logger.error(f"Coverage increment analysis failed: {e}")
            result['error'] = str(e)

        finally:
            # Clean up temporary worktrees
            for wt in [v05_worktree, gt_worktree]:
                if wt and os.path.exists(wt):
                    try:
                        self.repo.git.worktree('remove', '--force', wt)
                    except:
                        import shutil
                        shutil.rmtree(wt, ignore_errors=True)

        return result

    def _analyze_coverage_direct_with_worktrees(self,
                                                gt_commit: str,
                                                user_worktree: str,
                                                source_methods: List[Dict],
                                                test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        Run direct coverage comparison using temporary worktrees (new logic).

        Features:
        1. Does not run V-0.5 tests
        2. Only runs changed test methods on User and GT
        3. Only counts line/branch coverage on source methods changed in this diff
        """
        result = {
            'mode': 'direct',
            'line_overlap_ratio': 0.0,
            'branch_overlap_ratio': 0.0,
            # For compatibility with existing scoring logic, reuse these field names;
            # semantics change to: size of GT baseline coverage set
            'gt_increment_lines': 0,
            'gt_increment_branches': 0,
            'user_increment_lines': 0,
            'common_increment_lines': 0,
            'gt_has_increment': False,
            'error': None
        }

        gt_worktree = None

        try:
            gt_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_gt_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', gt_worktree, gt_commit)

            coverage_result = self.coverage_analyzer.analyze_gt_baseline(
                user_worktree=user_worktree,
                gt_worktree=gt_worktree,
                source_methods=source_methods,
                test_methods=test_methods
            )

            result['line_overlap_ratio'] = coverage_result['overlap_ratio']['line']
            result['branch_overlap_ratio'] = coverage_result['overlap_ratio']['branch']
            result['gt_increment_lines'] = len(coverage_result['gt_reference']['lines'])
            result['gt_increment_branches'] = len(coverage_result['gt_reference']['branches'])
            result['user_increment_lines'] = len(coverage_result['user_covered']['lines'])
            result['common_increment_lines'] = len(
                coverage_result['gt_reference']['lines'] &
                coverage_result['user_covered']['lines']
            )
            result['gt_has_increment'] = coverage_result.get('gt_has_reference', False)

        except Exception as e:
            logger.error(f"Direct coverage comparison failed: {e}")
            result['error'] = str(e)

        finally:
            if gt_worktree and os.path.exists(gt_worktree):
                try:
                    self.repo.git.worktree('remove', '--force', gt_worktree)
                except:
                    import shutil
                    shutil.rmtree(gt_worktree, ignore_errors=True)

        return result

    def run_batch_evaluation(self,
                              tasks: List[Dict],
                              output_file: str = None) -> Dict[str, Any]:
        """
        Run batch evaluation

        Args:
            tasks: list of evaluation tasks [{'project': str, 'gt_commit': str, 'user_worktree': str}]
            output_file: output file path

        Returns:
            dict: batch evaluation results
        """
        results = {
            'metadata': {
                'evaluation_time': datetime.now().isoformat(),
                'total_tasks': len(tasks),
                'successful': 0,
                'failed': 0
            },
            'results': []
        }

        for i, task in enumerate(tasks):
            logger.info(f"[{i+1}/{len(tasks)}] Running evaluation task...")

            try:
                worktree_path = task.get('user_worktree')
                gt_commit = task.get('gt_commit')

                if not worktree_path or not os.path.exists(worktree_path):
                    results['results'].append({
                        'gt_commit': gt_commit,
                        'status': 'failed',
                        'error': 'Worktree not found'
                    })
                    results['metadata']['failed'] += 1
                    continue

                if not gt_commit:
                    results['results'].append({
                        'status': 'failed',
                        'error': 'GT commit not specified'
                    })
                    results['metadata']['failed'] += 1
                    continue

                eval_result = self.run_evaluation(worktree_path, gt_commit)

                if eval_result.get('success'):
                    results['metadata']['successful'] += 1
                    eval_result['status'] = 'success'
                else:
                    results['metadata']['failed'] += 1
                    eval_result['status'] = 'failed'

                results['results'].append(eval_result)

            except Exception as e:
                logger.error(f"Evaluation task failed: {e}")
                results['results'].append({
                    'gt_commit': task.get('gt_commit'),
                    'status': 'failed',
                    'error': str(e)
                })
                results['metadata']['failed'] += 1

        # Save results
        if output_file:
            self._save_results(results, output_file)

        return results

    def _save_results(self, results: Dict, output_file: str):
        """Save evaluation results"""
        # Convert sets to lists for JSON serialization
        def convert_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            elif isinstance(obj, dict):
                return {k: convert_sets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_sets(item) for item in obj]
            return obj

        results = convert_sets(results)

        os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"Evaluation results saved to: {output_file}")

    def cleanup(self, worktree_path: str = None, cleanup_all: bool = False):
        """
        Clean up worktrees

        Args:
            worktree_path: specific worktree path to clean up
            cleanup_all: whether to clean up all evaluation worktrees
        """
        if cleanup_all:
            self.worktree_manager.cleanup_all_worktrees()
        elif worktree_path:
            self.worktree_manager.cleanup_worktree(worktree_path)
