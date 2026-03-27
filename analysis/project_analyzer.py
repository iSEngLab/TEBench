"""
Project analyzer - responsible for analyzing all commits in a single project
"""

import os
import json
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from config import Config, AnalysisConfig
from utils.logger import get_logger
from modules import GitAnalyzer, CommitFilter
from .commit_analyzer import CommitAnalyzer
from .cache_manager import CacheManager
from .report_generator import ReportGenerator

logger = get_logger()


@dataclass
class ProjectAnalysisResult:
    """Project analysis result"""

    project_info: Dict[str, Any] = field(default_factory=dict)
    filter_funnel: Dict[str, Any] = field(default_factory=dict)
    type_statistics: Dict[str, Any] = field(default_factory=dict)
    execution_statistics: Dict[str, Any] = field(default_factory=dict)
    qualified_commits: List[str] = field(default_factory=list)
    analysis_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


class ProjectAnalyzer:
    """Project analyzer"""

    def __init__(self,
                 project_path: str,
                 output_dir: str,
                 workers: int = 4,
                 resume: bool = False,
                 enable_cache: bool = True,
                 verbose: bool = False):
        """
        Initialize the project analyzer

        Args:
            project_path: project path
            output_dir: output directory
            workers: number of concurrent workers
            resume: whether to resume from checkpoint
            enable_cache: whether to enable cache
            verbose: verbose logging
        """
        self.project_path = project_path
        self.project_name = os.path.basename(project_path)
        self.output_dir = output_dir
        self.workers = workers
        self.resume = resume
        self.verbose = verbose

        # Initialize components
        self.git_analyzer = GitAnalyzer(project_path)
        self.commit_filter = CommitFilter()
        self.cache_manager = CacheManager(
            cache_dir=os.path.join(AnalysisConfig.CACHE_DIR, self.project_name),
            enabled=enable_cache
        )
        self.report_generator = ReportGenerator(output_dir)

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, 'commits'), exist_ok=True)

        # Statistics data
        self._stats = {
            'total_commits': 0,
            'after_date_filter': 0,
            'has_test_and_source': 0,
            'has_method_changes': 0,
            'v1_build_success': 0,
            'v0_build_success': 0,
            'qualified': 0,
            'from_cache': 0,
            'errors': []
        }

    def analyze(self,
                since_date: str = None,
                sample: int = None,
                phase: str = 'full',
                single_commit: str = None) -> ProjectAnalysisResult:
        """
        Execute project analysis

        Args:
            since_date: start date (YYYY-MM-DD)
            sample: sample size
            phase: execution phase ('quick', 'method', 'full')
            single_commit: only analyze the specified commit

        Returns:
            project analysis result
        """
        start_time = datetime.now()
        logger.info(f"Starting analysis of project: {self.project_name}")
        logger.info(f"Analysis phase: {phase}")

        result = ProjectAnalysisResult()

        try:
            # Collect project information
            result.project_info = self._collect_project_info(since_date)
            if result.project_info.get('total_commits') is not None:
                self._stats['total_commits'] = result.project_info.get('total_commits', 0)

            # Phase 1: Quick scan
            logger.info("\n[Phase 1] Quick scan...")
            if single_commit:
                candidates = [single_commit]
                self._stats['total_commits'] = 1
                self._stats['after_date_filter'] = 1
            else:
                candidates = self._phase1_quick_scan(since_date)

            logger.info(f"  Candidate commits: {len(candidates)}")

            if phase == 'quick':
                # Quick scan only, save intermediate result
                self._save_phase_result('phase1', candidates)
                result.filter_funnel = self._build_filter_funnel()
                return result

            # Phase 2: Method analysis
            logger.info("\n[Phase 2] Method-level analysis...")
            method_analyzed = self._phase2_method_analysis(candidates, sample)
            logger.info(f"  Commits with method changes: {len(method_analyzed)}")

            if phase == 'method':
                # Save intermediate result
                self._save_phase_result('phase2', method_analyzed)
                result.filter_funnel = self._build_filter_funnel()
                return result

            # Phase 3: Execution analysis
            logger.info("\n[Phase 3] Execution analysis...")
            execution_results = self._phase3_execution_analysis(method_analyzed)

            # Phase 4: Classification
            logger.info("\n[Phase 4] Classification...")
            classified_results = self._phase4_classification(execution_results)

            # Phase 5: Report generation
            logger.info("\n[Phase 5] Generating report...")
            result = self._phase5_report_generation(classified_results, start_time, since_date)

            return result

        except Exception as e:
            logger.error(f"Project analysis failed: {e}", exc_info=self.verbose)
            result.analysis_metadata['error'] = str(e)
            return result

    def _collect_project_info(self, since_date: str) -> dict:
        """Collect basic project information"""
        repo = self.git_analyzer.repo

        # Get all commits for statistics
        all_commits = list(repo.iter_commits('HEAD'))

        # Date range
        dates = [datetime.fromtimestamp(c.committed_date) for c in all_commits]

        return {
            'name': self.project_name,
            'path': self.project_path,
            'default_branch': repo.active_branch.name if not repo.head.is_detached else 'HEAD',
            'total_commits': len(all_commits),
            'date_range': {
                'earliest': min(dates).strftime('%Y-%m-%d') if dates else None,
                'latest': max(dates).strftime('%Y-%m-%d') if dates else None,
                'filter_since': since_date
            }
        }

    def _phase1_quick_scan(self, since_date: str) -> List[str]:
        """
        Phase 1: Quick scan
        Only checks file changes, filters commits that modify both test and source code
        """
        # Parse date
        date_filter = None
        if since_date:
            try:
                date_filter = datetime.strptime(since_date, "%Y-%m-%d")
            except:
                logger.warning(f"Invalid date format: {since_date}")

        # Get all commits
        commits = self.git_analyzer.get_all_commits(since_date=date_filter)
        self._stats['total_commits'] = len(commits) if not date_filter else self._stats['total_commits']
        self._stats['after_date_filter'] = len(commits)

        candidates = []
        for i, commit in enumerate(commits):
            if i % 100 == 0:
                logger.debug(f"  Scan progress: {i}/{len(commits)}")

            # Get changed files
            changed_files = self.git_analyzer.get_changed_files(commit)

            # Check if both test and source code were modified
            if self.commit_filter.filter_by_file_changes(changed_files):
                candidates.append(commit.hexsha)

        self._stats['has_test_and_source'] = len(candidates)
        return candidates

    def _phase2_method_analysis(self, candidates: List[str], sample: int = None) -> List[dict]:
        """
        Phase 2: Method-level analysis
        Analyzes method changes in each commit
        """
        if sample and len(candidates) > sample:
            logger.info(f"  Sampling {sample} commits")
            import random
            candidates = random.sample(candidates, sample)

        analyzed = []

        for i, commit_hash in enumerate(candidates):
            if i % 20 == 0:
                logger.debug(f"  Method analysis progress: {i}/{len(candidates)}")

            # Check cache
            if self.resume and self.cache_manager.has_cache(
                self.project_name, commit_hash, 'method'
            ):
                cached = self.cache_manager.get_cache(
                    self.project_name, commit_hash, 'method'
                )
                if cached and cached.get('data'):
                    analyzed.append(cached['data'])
                    self._stats['from_cache'] += 1
                    continue

            try:
                # Create commit analyzer and perform method analysis
                commit_analyzer = CommitAnalyzer(
                    repo_path=self.project_path,
                    output_dir=self.output_dir
                )

                method_info = commit_analyzer.analyze_methods(commit_hash)

                if method_info and method_info.get('has_method_changes'):
                    analyzed.append(method_info)

                    # Cache result
                    self.cache_manager.set_cache(
                        self.project_name, commit_hash, 'method', method_info
                    )

            except Exception as e:
                logger.debug(f"  Method analysis failed {commit_hash[:8]}: {e}")
                self._stats['errors'].append({
                    'commit': commit_hash,
                    'phase': 'method_analysis',
                    'error': str(e)
                })

        self._stats['has_method_changes'] = len(analyzed)
        return analyzed

    def _phase3_execution_analysis(self, method_analyzed: List[dict]) -> List[dict]:
        """
        Phase 3: Execution analysis
        Concurrently builds and tests 4 versions
        """
        results = []

        # Filter already-cached items
        to_process = []
        for info in method_analyzed:
            commit_hash = info['commit_hash']

            if self.resume and self.cache_manager.has_cache(
                self.project_name, commit_hash, 'execution'
            ):
                cached = self.cache_manager.get_cache(
                    self.project_name, commit_hash, 'execution'
                )
                if cached and cached.get('data'):
                    cached_data = cached['data']
                    results.append(cached_data)
                    self._stats['from_cache'] += 1
                    if cached_data.get('v1_execution', {}).get('build', {}).get('success'):
                        self._stats['v1_build_success'] += 1
                    if cached_data.get('v0_execution', {}).get('build', {}).get('success'):
                        self._stats['v0_build_success'] += 1
                    # Ensure the output directory has the corresponding commit result
                    self._save_commit_result(commit_hash, cached_data)
                    continue

            to_process.append(info)

        logger.info(f"  Commits requiring execution analysis: {len(to_process)} (cached: {len(results)})")

        if not to_process:
            return results

        def _process_sequential(items: List[dict]) -> List[dict]:
            seq_results = []
            completed = 0
            for info in items:
                commit_hash = info['commit_hash']
                completed += 1
                try:
                    result = _process_single_commit_execution(
                        self.project_path,
                        self.output_dir,
                        info
                    )
                    if result:
                        seq_results.append(result)
                        if result.get('v1_execution', {}).get('build', {}).get('success'):
                            self._stats['v1_build_success'] += 1
                        if result.get('v0_execution', {}).get('build', {}).get('success'):
                            self._stats['v0_build_success'] += 1
                        self.cache_manager.set_cache(
                            self.project_name, commit_hash, 'execution', result
                        )
                        self._save_commit_result(commit_hash, result)
                    status = "\u2713" if result and result.get('qualified') else "\u2717"
                    logger.info(f"  [{completed}/{len(items)}] {commit_hash[:8]} {status}")
                except Exception as e:
                    logger.error(f"  [{completed}/{len(items)}] {commit_hash[:8]} failed: {e}")
                    self._stats['errors'].append({
                        'commit': commit_hash,
                        'phase': 'execution',
                        'error': str(e)
                    })
            return seq_results

        if self.workers <= 1:
            results.extend(_process_sequential(to_process))
            return results

        # Concurrent processing
        try:
            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                futures = {}

                for info in to_process:
                    future = executor.submit(
                        _process_single_commit_execution,
                        self.project_path,
                        self.output_dir,
                        info
                    )
                    futures[future] = info['commit_hash']

                completed = 0
                for future in as_completed(futures):
                    commit_hash = futures[future]
                    completed += 1

                    try:
                        result = future.result(timeout=AnalysisConfig.COMMIT_TIMEOUT)

                        if result:
                            results.append(result)

                            # Update statistics
                            if result.get('v1_execution', {}).get('build', {}).get('success'):
                                self._stats['v1_build_success'] += 1
                            if result.get('v0_execution', {}).get('build', {}).get('success'):
                                self._stats['v0_build_success'] += 1

                            # Cache result
                            self.cache_manager.set_cache(
                                self.project_name, commit_hash, 'execution', result
                            )

                            # Save commit details
                            self._save_commit_result(commit_hash, result)

                        status = "\u2713" if result and result.get('qualified') else "\u2717"
                        logger.info(f"  [{completed}/{len(to_process)}] {commit_hash[:8]} {status}")

                    except Exception as e:
                        logger.error(f"  [{completed}/{len(to_process)}] {commit_hash[:8]} failed: {e}")
                        self._stats['errors'].append({
                            'commit': commit_hash,
                            'phase': 'execution',
                            'error': str(e)
                        })
        except PermissionError as e:
            logger.warning(f"ProcessPool unavailable, falling back to sequential execution: {e}")
            results.extend(_process_sequential(to_process))

        return results

    def _phase4_classification(self, execution_results: List[dict]) -> List[dict]:
        """
        Phase 4: Classification
        """
        classified = []

        for result in execution_results:
            # Check if qualified
            def _test_pass(execution: dict) -> bool:
                test_info = execution.get('test', {})
                status = test_info.get('status')
                if status:
                    return status == 'pass'
                return test_info.get('success', False)

            v1_ok = result.get('v1_execution', {}).get('build', {}).get('success', False) and \
                    _test_pass(result.get('v1_execution', {}))
            v0_ok = result.get('v0_execution', {}).get('build', {}).get('success', False) and \
                    _test_pass(result.get('v0_execution', {}))

            if not (v1_ok and v0_ok):
                result['qualified'] = False
                continue

            result['qualified'] = True
            self._stats['qualified'] += 1

            # Classify
            classification = self._classify_commit(result)
            result['classification'] = classification

            classified.append(result)

        return classified

    def _classify_commit(self, result: dict) -> dict:
        """Classify a single commit"""
        from modules.commit_classifier import CommitClassifier

        classifier = CommitClassifier(
            coverage_threshold=AnalysisConfig.COVERAGE_DECREASE_THRESHOLD
        )

        return classifier.classify(
            v1_result=result.get('v1_execution', {}),
            v05_result=result.get('v05_execution', {}),
            t05_result=result.get('t05_execution', {}),
            v0_result=result.get('v0_execution', {})
        )

    def _phase5_report_generation(self, classified_results: List[dict],
                                  start_time: datetime,
                                  since_date: Optional[str] = None) -> ProjectAnalysisResult:
        """
        Phase 5: Report generation
        """
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        result = ProjectAnalysisResult()

        # Project information
        result.project_info = self._collect_project_info(since_date)

        # Filter funnel
        result.filter_funnel = self._build_filter_funnel()

        # Type statistics
        result.type_statistics = self._build_type_statistics(classified_results)

        # Execution statistics
        result.execution_statistics = self._build_execution_statistics(classified_results)

        # Qualified commits list (with classification info)
        result.qualified_commits = []
        for r in classified_results:
            if r.get('qualified'):
                primary_type = r.get('classification', {}).get('primary_type', '')
                result.qualified_commits.append({
                    'commit_hash': r['commit_hash'],
                    'primary_type': primary_type
                })

        # Metadata
        result.analysis_metadata = {
            'analysis_start_time': start_time.isoformat(),
            'analysis_end_time': end_time.isoformat(),
            'total_duration_seconds': duration,
            'workers_used': self.workers,
            'commits_analyzed': len(classified_results),
            'commits_from_cache': self._stats['from_cache'],
            'errors_count': len(self._stats['errors'])
        }

        # Generate report files
        self.report_generator.generate_project_summary_json(
            result,
            os.path.join(self.output_dir, 'analysis_result.json')
        )

        self.report_generator.generate_project_summary_markdown(
            result,
            os.path.join(self.output_dir, 'summary.md')
        )

        return result

    def _build_filter_funnel(self) -> dict:
        """Build filter funnel statistics"""
        stats = self._stats

        def rate(num, denom):
            if denom == 0:
                return "0.0%"
            return f"{(num/denom*100):.1f}%"

        return {
            'stage0_total': stats['total_commits'],
            'stage1_after_date_filter': stats['after_date_filter'],
            'stage2_has_test_and_source': stats['has_test_and_source'],
            'stage3_has_method_changes': stats['has_method_changes'],
            'stage4_v1_build_success': stats['v1_build_success'],
            'stage5_v0_build_success': stats['v0_build_success'],
            'stage6_qualified': stats['qualified'],
            'filter_rates': {
                'date_filter': rate(stats['after_date_filter'], stats['total_commits']),
                'file_change_filter': rate(stats['has_test_and_source'], stats['after_date_filter']),
                'method_change_filter': rate(stats['has_method_changes'], stats['has_test_and_source']),
                'v1_build_filter': rate(stats['v1_build_success'], stats['has_method_changes']),
                'v0_build_filter': rate(stats['v0_build_success'], stats['v1_build_success']),
                'overall': rate(stats['qualified'], stats['total_commits'])
            }
        }

    def _build_type_statistics(self, results: List[dict]) -> dict:
        """Build type statistics"""
        type1_count = 0
        type1_compile = 0
        type1_runtime = 0
        type1_test_compile = 0
        type2_count = 0
        type3_count = 0

        line_coverage_gains = []
        branch_coverage_gains = []
        scenarios = {'A': 0, 'B': 0, 'C': 0, 'D': 0}

        type1_examples = []
        type2_examples = []
        type3_examples = []

        for r in results:
            if not r.get('qualified'):
                continue

            c = r.get('classification', {})

            # Scenario statistics
            scenario = c.get('scenario', 'D')
            scenarios[scenario] = scenarios.get(scenario, 0) + 1

            # Type1
            if c.get('type1_execution_error', {}).get('detected'):
                type1_count += 1
                subtype = c['type1_execution_error'].get('subtype')
                if subtype == 'compile_failure':
                    type1_compile += 1
                elif subtype == 'test_compile_failure':
                    type1_test_compile += 1
                else:
                    type1_runtime += 1
                if len(type1_examples) < 3:
                    type1_examples.append(r['commit_hash'])

            # Type2
            if c.get('type2_coverage_decrease', {}).get('detected'):
                type2_count += 1
                evidence = c['type2_coverage_decrease'].get('evidence', {})
                if 'coverage_diff' in evidence:
                    line_coverage_gains.append(evidence['coverage_diff'])
                if 'branch_coverage_diff' in evidence:
                    branch_coverage_gains.append(evidence['branch_coverage_diff'])
                if len(type2_examples) < 3:
                    type2_examples.append(r['commit_hash'])

            # Type3
            if c.get('type3_adaptive_change', {}).get('detected'):
                type3_count += 1
                if len(type3_examples) < 3:
                    type3_examples.append(r['commit_hash'])

        total = len([r for r in results if r.get('qualified')])

        def pct(n):
            return f"{(n/total*100):.1f}%" if total > 0 else "0.0%"

        return {
            'type1_execution_error': {
                'count': type1_count,
                'percentage': pct(type1_count),
                'subtypes': {
                    'compile_failure': type1_compile,
                    'runtime_failure': type1_runtime,
                    'test_compile_failure': type1_test_compile
                },
                'examples': type1_examples
            },
            'type2_coverage_decrease': {
                'count': type2_count,
                'percentage': pct(type2_count),
                'avg_line_coverage_gain': sum(line_coverage_gains) / len(line_coverage_gains) if line_coverage_gains else 0,
                'avg_branch_coverage_gain': sum(branch_coverage_gains) / len(branch_coverage_gains) if branch_coverage_gains else 0,
                'avg_coverage_decrease': sum(line_coverage_gains) / len(line_coverage_gains) if line_coverage_gains else 0,
                'examples': type2_examples
            },
            'type3_adaptive_change': {
                'count': type3_count,
                'percentage': pct(type3_count),
                'examples': type3_examples
            },
            'scenario_distribution': scenarios
        }

    def _build_execution_statistics(self, results: List[dict]) -> dict:
        """Build execution statistics"""
        v05_compile_success = 0
        v05_test_success = 0
        t05_compile_success = 0
        t05_test_success = 0

        for r in results:
            v05 = r.get('v05_execution', {})
            t05 = r.get('t05_execution', {})

            if v05.get('build', {}).get('success'):
                v05_compile_success += 1
            if v05.get('test', {}).get('status') == 'pass' or v05.get('test', {}).get('success'):
                v05_test_success += 1
            if t05.get('build', {}).get('success'):
                t05_compile_success += 1
            if t05.get('test', {}).get('status') == 'pass' or t05.get('test', {}).get('success'):
                t05_test_success += 1

        return {
            'v05_results': {
                'compile_success': v05_compile_success,
                'compile_failed': len(results) - v05_compile_success,
                'test_success': v05_test_success,
                'test_failed': v05_compile_success - v05_test_success
            },
            't05_results': {
                'compile_success': t05_compile_success,
                'compile_failed': len(results) - t05_compile_success,
                'test_success': t05_test_success,
                'test_failed': t05_compile_success - t05_test_success
            }
        }

    def _save_phase_result(self, phase: str, data: List):
        """Save phase result"""
        output_path = os.path.join(self.output_dir, f'{phase}_result.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                'phase': phase,
                'timestamp': datetime.now().isoformat(),
                'count': len(data),
                'data': data
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"  Phase result saved: {output_path}")

    def _save_commit_result(self, commit_hash: str, result: dict):
        """Save analysis result for a single commit"""
        # Get classification type (used as directory name prefix)
        classification = result.get('classification', {})
        primary_type = classification.get('primary_type', '')

        # Extract type number (type1_execution_error -> type1, type2_coverage_decrease -> type2, etc.)
        type_prefix = ''
        if primary_type:
            if primary_type.startswith('type1'):
                type_prefix = 'type1_'
            elif primary_type.startswith('type2'):
                type_prefix = 'type2_'
            elif primary_type.startswith('type3'):
                type_prefix = 'type3_'

        # Use first 8 characters as directory name (sufficient for unique identification), with type prefix
        short_hash = commit_hash[:8]
        dir_name = f"{type_prefix}{short_hash}" if type_prefix else short_hash
        commit_dir = os.path.join(self.output_dir, 'commits', dir_name)
        os.makedirs(commit_dir, exist_ok=True)

        # JSON file placed in commit directory, named detail.json
        output_path = os.path.join(commit_dir, 'detail.json')
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Save diff files
        diff_info = result.get('diff_info', {})
        self._write_diff_file(commit_dir, 'full.diff', diff_info.get('full_diff'))
        self._write_diff_file(commit_dir, 'source_only.diff', diff_info.get('source_only_diff'))
        self._write_diff_file(commit_dir, 'test_only.diff', diff_info.get('test_only_diff'))

        # Generate visualization-friendly summary
        self.report_generator.generate_commit_summary_markdown(
            result,
            os.path.join(commit_dir, 'summary.md')
        )

    def _write_diff_file(self, commit_dir: str, filename: str, content: str):
        """Write diff file for syntax-highlighted viewing in editors"""
        if content is None:
            return
        path = os.path.join(commit_dir, filename)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logger.debug(f"Failed to write diff {path}: {e}")


def _process_single_commit_execution(repo_path: str, output_dir: str, method_info: dict) -> dict:
    """
    Process execution analysis for a single commit (runs in an isolated process)
    """
    from .commit_analyzer import CommitAnalyzer

    commit_analyzer = CommitAnalyzer(
        repo_path=repo_path,
        output_dir=output_dir
    )

    try:
        return commit_analyzer.analyze_execution(method_info)
    except Exception as e:
        logger.error(f"Execution analysis failed {method_info['commit_hash'][:8]}: {e}")
        return None
