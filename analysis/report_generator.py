"""
Report generator - generates analysis reports in various formats
"""

import os
import json
from datetime import datetime
from typing import List, Dict, Any

from utils.logger import get_logger

logger = get_logger()


class ReportGenerator:
    """Report generator"""

    def __init__(self, output_dir: str):
        """
        Initialize

        Args:
            output_dir: output directory
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_project_summary_json(self, result: 'ProjectAnalysisResult', output_path: str):
        """Generate project JSON summary"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"JSON report generated: {output_path}")
        except Exception as e:
            logger.error(f"Failed to generate JSON report: {e}")

    def generate_project_summary_markdown(self, result: 'ProjectAnalysisResult', output_path: str):
        """Generate project Markdown report"""
        try:
            md_content = self._build_project_markdown(result)

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            logger.info(f"Markdown report generated: {output_path}")
        except Exception as e:
            logger.error(f"Failed to generate Markdown report: {e}")

    def _build_project_markdown(self, result: 'ProjectAnalysisResult') -> str:
        """Build project Markdown content"""
        lines = []

        project_info = result.project_info
        filter_funnel = result.filter_funnel
        type_stats = result.type_statistics
        exec_stats = result.execution_statistics
        metadata = result.analysis_metadata

        # Title
        lines.append(f"# {project_info.get('name', 'Unknown')} Analysis Report\n")

        # Project information
        lines.append("## Project Information\n")
        lines.append(f"- **Project Name**: {project_info.get('name')}")
        lines.append(f"- **Path**: {project_info.get('path')}")
        lines.append(f"- **Default Branch**: {project_info.get('default_branch')}")
        lines.append(f"- **Analysis Date**: {metadata.get('analysis_start_time', '')[:10]}")

        duration = metadata.get('total_duration_seconds', 0)
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        if hours > 0:
            lines.append(f"- **Analysis Duration**: {hours}h {minutes}m {seconds}s")
        elif minutes > 0:
            lines.append(f"- **Analysis Duration**: {minutes}m {seconds}s")
        else:
            lines.append(f"- **Analysis Duration**: {seconds}s")
        lines.append("")

        # Filter funnel
        lines.append("## Filter Funnel\n")
        lines.append("| Stage | Count | Stage Pass Rate | Cumulative Pass Rate |")
        lines.append("|-------|-------|-----------------|----------------------|")

        # Get counts at each stage
        total = filter_funnel.get('stage0_total', 0)
        after_date = filter_funnel.get('stage1_after_date_filter', 0)
        has_test_src = filter_funnel.get('stage2_has_test_and_source', 0)
        has_method = filter_funnel.get('stage3_has_method_changes', 0)
        v1_build = filter_funnel.get('stage4_v1_build_success', 0)
        v0_build = filter_funnel.get('stage5_v0_build_success', 0)
        qualified = filter_funnel.get('stage6_qualified', 0)

        def pct(num, denom):
            return f"{num/denom*100:.1f}%" if denom > 0 else "-"

        # If total is 0, use after_date as baseline
        base_total = total if total > 0 else after_date

        lines.append(f"| Commits within date range | {after_date} | - | - |")
        lines.append(f"| Modify both test and source | {has_test_src} | {pct(has_test_src, after_date)} | {pct(has_test_src, base_total)} |")
        lines.append(f"| Has method-level changes | {has_method} | {pct(has_method, has_test_src)} | {pct(has_method, base_total)} |")
        lines.append(f"| V-1 compile success | {v1_build} | {pct(v1_build, has_method)} | {pct(v1_build, base_total)} |")
        lines.append(f"| V0 compile success | {v0_build} | {pct(v0_build, v1_build)} | {pct(v0_build, base_total)} |")
        lines.append(f"| **Finally qualified** | {qualified} | {pct(qualified, v0_build)} | {pct(qualified, base_total)} |")
        lines.append("")
        lines.append("*Note: final qualification requires both V-1 and V0 to compile and pass tests*\n")

        # Type distribution
        lines.append("## Type Distribution\n")
        lines.append("| Type | Count | Percentage | Description |")
        lines.append("|------|-------|------------|-------------|")

        type1 = type_stats.get('type1_execution_error', {})
        type2 = type_stats.get('type2_coverage_decrease', {})
        type3 = type_stats.get('type3_adaptive_change', {})

        lines.append(f"| Type1 (execution error) | {type1.get('count', 0)} | {type1.get('percentage', '0%')} | V-0.5 compile or test failure |")

        subtypes = type1.get('subtypes', {})
        lines.append(f"| ├─ Compile failure | {subtypes.get('compile_failure', 0)} | - | |")
        lines.append(f"| ├─ Test compile failure | {subtypes.get('test_compile_failure', 0)} | - | |")
        lines.append(f"| └─ Runtime failure | {subtypes.get('runtime_failure', 0)} | - | |")

        lines.append(f"| Type2 (coverage gap) | {type2.get('count', 0)} | {type2.get('percentage', '0%')} | V0 coverage higher than V-0.5 |")
        lines.append(f"| Type3 (adaptive change) | {type3.get('count', 0)} | {type3.get('percentage', '0%')} | Other cases |")
        lines.append("")

        # Scenario distribution
        lines.append("## Scenario Distribution\n")
        lines.append("Scenarios are classified based on test execution results of V-0.5 and T-0.5 (both V-1 and V0 have passed build and test):\n")
        lines.append("| Scenario | V-0.5 | T-0.5 | Count | Description |")
        lines.append("|----------|-------|-------|-------|-------------|")

        scenarios = type_stats.get('scenario_distribution', {})
        lines.append(f"| A | fail | fail | {scenarios.get('A', 0)} | Neither new nor old tests compatible with old code |")
        lines.append(f"| B | fail | pass | {scenarios.get('B', 0)} | Old tests fail, new tests can run on old code |")
        lines.append(f"| C | pass | fail | {scenarios.get('C', 0)} | Old tests pass, new tests target new functionality |")
        lines.append(f"| D | pass | pass | {scenarios.get('D', 0)} | Both new and old tests pass |")
        if scenarios.get('U', 0) > 0:
            lines.append(f"| U | ? | ? | {scenarios.get('U', 0)} | V-0.5 or T-0.5 test skipped / result unknown |")
        lines.append("")

        # V-0.5 and T-0.5 execution statistics
        lines.append("## Execution Statistics\n")
        lines.append("### V-0.5 (source changes only)\n")
        v05 = exec_stats.get('v05_results', {})
        lines.append(f"- Compile success: {v05.get('compile_success', 0)}")
        lines.append(f"- Compile failed: {v05.get('compile_failed', 0)}")
        lines.append(f"- Test success: {v05.get('test_success', 0)}")
        lines.append(f"- Test failed: {v05.get('test_failed', 0)}")
        lines.append("")

        lines.append("### T-0.5 (test changes only)\n")
        t05 = exec_stats.get('t05_results', {})
        lines.append(f"- Compile success: {t05.get('compile_success', 0)}")
        lines.append(f"- Compile failed: {t05.get('compile_failed', 0)}")
        lines.append(f"- Test success: {t05.get('test_success', 0)}")
        lines.append(f"- Test failed: {t05.get('test_failed', 0)}")
        lines.append("")

        # Example commits
        lines.append("## Example Commits\n")

        if type1.get('examples'):
            lines.append("### Type1 Examples (execution error)\n")
            for i, commit in enumerate(type1['examples'][:3], 1):
                short = commit[:8]
                lines.append(f"{i}. [{short}](commits/type1_{short}/summary.md)")
            lines.append("")

        if type2.get('examples'):
            lines.append("### Type2 Examples (coverage gap)\n")
            for i, commit in enumerate(type2['examples'][:3], 1):
                short = commit[:8]
                lines.append(f"{i}. [{short}](commits/type2_{short}/summary.md)")
            lines.append("")

        if type3.get('examples'):
            lines.append("### Type3 Examples (adaptive change)\n")
            for i, commit in enumerate(type3['examples'][:3], 1):
                short = commit[:8]
                lines.append(f"{i}. [{short}](commits/type3_{short}/summary.md)")
            lines.append("")

        # Qualified commits list
        qualified = result.qualified_commits
        lines.append(f"## Qualified Commits List ({len(qualified)} total)\n")

        def _get_commit_link(commit_info):
            """Generate commit link, supporting both new and old data formats"""
            if isinstance(commit_info, dict):
                short = commit_info['commit_hash'][:8]
                primary_type = commit_info.get('primary_type', '')
                if primary_type.startswith('type1'):
                    return f"[{short}](commits/type1_{short}/summary.md)"
                elif primary_type.startswith('type2'):
                    return f"[{short}](commits/type2_{short}/summary.md)"
                elif primary_type.startswith('type3'):
                    return f"[{short}](commits/type3_{short}/summary.md)"
                else:
                    return f"[{short}](commits/{short}/summary.md)"
            else:
                # Compatible with old format (plain string)
                short = commit_info[:8]
                return f"[{short}](commits/{short}/summary.md)"

        if len(qualified) <= 20:
            for commit in qualified:
                lines.append(f"- {_get_commit_link(commit)}")
        else:
            lines.append("<details>")
            lines.append(f"<summary>Click to expand full list ({len(qualified)} total)</summary>\n")
            for commit in qualified:
                lines.append(f"- {_get_commit_link(commit)}")
            lines.append("\n</details>")
        lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("*Generated by TUBench Analysis Tool*")

        return '\n'.join(lines)

    def generate_commit_detail_json(self, result: 'CommitAnalysisResult', output_path: str):
        """Generate commit detail JSON"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to generate commit JSON: {e}")

    def generate_commit_summary_markdown(self, commit_result: dict, output_path: str):
        """Generate commit summary Markdown for quick review of execution and coverage"""
        try:
            basic = commit_result.get('basic_info', {})
            v1 = commit_result.get('v1_execution', {})
            v05 = commit_result.get('v05_execution', {})
            t05 = commit_result.get('t05_execution', {})
            v0 = commit_result.get('v0_execution', {})
            file_changes = commit_result.get('file_changes', {})
            method_changes = commit_result.get('method_changes', {})
            diff_info = commit_result.get('diff_info', {})
            method_change_stats = commit_result.get('method_change_stats', {}) or \
                method_changes.get('method_change_stats', {})

            def _fmt_status(val, skipped=False, status=None):
                if status == 'skip':
                    return "SKIP"
                if status == 'error':
                    return "ERROR"
                if skipped:
                    return "SKIP"
                return "PASS" if val else "FAIL"

            def _cov_method(cov):
                line_cov = cov.get('method_line_coverage') if cov else None
                if not line_cov or line_cov.get('total_lines', 0) == 0:
                    return "-"
                return f"{line_cov.get('coverage_ratio', 0):.4f} ({line_cov.get('covered_lines', 0)}/{line_cov.get('total_lines', 0)})"

            def _cov_branch(cov):
                branch_cov = cov.get('method_branch_coverage') if cov else None
                if not branch_cov or branch_cov.get('total_branches', 0) == 0:
                    return "-"
                return f"{branch_cov.get('coverage_ratio', 0):.4f} ({branch_cov.get('covered_branches', 0)}/{branch_cov.get('total_branches', 0)})"

            def _err_msg(data):
                build_data = data.get('build', {})
                build_err = build_data.get('error_message')
                test_data = data.get('test', {})
                test_err = test_data.get('error_message')
                test_status = test_data.get('status')

                # Check for compatibility issues
                compat_issues = build_data.get('compatibility_issues')
                if compat_issues:
                    # Extract the first compatibility issue as a short hint
                    first_issue = compat_issues.split('\n')[0] if '\n' in compat_issues else compat_issues
                    return f"\u26a0\ufe0f {first_issue}"[:200]

                if test_status == 'skip':
                    return (test_err or 'Skipped')[:200]
                if test_data.get('selection_skipped'):
                    return test_err or 'Skipped'
                if build_err:
                    # Remove COMPATIBILITY ISSUES DETECTED header, show only actual error
                    if '[COMPATIBILITY ISSUES DETECTED]' in build_err:
                        lines_list = build_err.split('\n')
                        # Find the first non-compatibility-hint error line
                        for line in lines_list:
                            if line.strip() and not line.startswith('\u26a0\ufe0f') and 'COMPATIBILITY' not in line:
                                return line.strip()[:200]
                    return build_err.strip().split('\n')[0][:200]
                if test_err:
                    return test_err.strip().split('\n')[0][:200]

                # Check for failed tests
                failed_tests = test_data.get('failed_tests', [])
                if failed_tests:
                    # Show number of failed tests and name of first failure
                    first_fail = failed_tests[0] if isinstance(failed_tests[0], str) else failed_tests[0].get('full_name', str(failed_tests[0]))
                    if len(failed_tests) == 1:
                        return f"Test failed: {first_fail}"[:200]
                    else:
                        return f"{len(failed_tests)} tests failed: {first_fail}..."[:200]

                # Check if test failed but no specific error message
                if not test_data.get('success', True) and test_data.get('failed', 0) > 0:
                    return f"{test_data.get('failed', 0)} test(s) failed"

                return "-"

            lines = []
            lines.append(f"# Commit {basic.get('short_hash', '')}\n")
            lines.append(f"- **Commit**: `{basic.get('commit_hash', '')}`")
            lines.append(f"- **Parent**: `{basic.get('parent_hash', '')}`")
            lines.append(f"- **Author**: {basic.get('author', '')}")
            lines.append(f"- **Date**: {basic.get('date', '')}")
            lines.append(f"- **Message**: {basic.get('message_subject', '')}")
            lines.append("")

            def _count_selected_test_methods(selectors: list) -> int:
                """Count the actual number of selected test methods from Surefire selector list

                Selector format:
                - "ClassName#method1+method2+method3" -> 3 methods
                - "ClassName" (whole class) -> counts as 1 selector
                """
                count = 0
                for selector in selectors:
                    if '#' in selector:
                        # Format: ClassName#method1+method2+...
                        methods_part = selector.split('#', 1)[1]
                        count += len(methods_part.split('+'))
                    else:
                        # Whole class, count as 1
                        count += 1
                return count

            def _version_status(data):
                build_ok = data.get('build', {}).get('success', False)
                test_info = data.get('test', {})
                test_status = test_info.get('status')
                if not test_status:
                    test_status = 'pass' if test_info.get('success') else 'fail'
                return f"build={_fmt_status(build_ok)}, test={_fmt_status(test_info.get('success', False), test_info.get('selection_skipped', False), test_status)}"

            classification = commit_result.get('classification', {})

            lines.append("## Summary\n")
            lines.append(f"- **Qualified**: {commit_result.get('qualified', False)}")
            if classification:
                lines.append(f"- **Primary Type**: {classification.get('primary_type', '-')}")
                lines.append(f"- **Scenario**: {classification.get('scenario', '-')}")
            lines.append(f"- **V-1**: {_version_status(v1)}")
            lines.append(f"- **V-0.5**: {_version_status(v05)}")
            lines.append(f"- **T-0.5**: {_version_status(t05)}")
            lines.append(f"- **V0**: {_version_status(v0)}")
            lines.append("")

            def _emit_version_section(label, desc, data, commit_hash=None):
                build = data.get('build', {})
                test = data.get('test', {})
                cov = data.get('coverage', {})
                test_status = test.get('status')
                if not test_status:
                    test_status = 'pass' if test.get('success') else 'fail'

                lines.append(f"## {label} - {desc}\n")
                if commit_hash:
                    lines.append(f"- **Commit**: `{commit_hash}`")
                lines.append(f"- **Build**: {_fmt_status(build.get('success', False))} ({build.get('duration_seconds', 0)}s)")
                if build.get('command'):
                    lines.append(f"- **Build Command**: `{build.get('command')}`")
                if build.get('compatibility_issues'):
                    lines.append(f"- **Build Compatibility Issues**: {build.get('compatibility_issues')}")
                if build.get('error_message'):
                    lines.append(f"- **Build Error**: {build.get('error_message')}")
                if build.get('compile_errors'):
                    lines.append("- **Compile Errors**:")
                    lines.append("```")
                    for err in build.get('compile_errors', []):
                        lines.append(f"{err.get('file','')}: {err.get('message','')}")
                    lines.append("```")

                lines.append(f"- **Test**: {_fmt_status(test.get('success', False), test.get('selection_skipped', False), test_status)} ({test.get('duration_seconds', 0)}s)")
                total_tests = test.get('total_tests', 0)
                if total_tests:
                    lines.append(f"- **Test Summary**: total={total_tests}, passed={test.get('passed', 0)}, failed={test.get('failed', 0)}, errors={test.get('errors', 0)}, skipped={test.get('skipped', 0)}")
                if test.get('selection_skipped'):
                    lines.append("- **Test Selection**: skipped (no changed tests identified)")
                selected_tests = test.get('selected_tests', []) or []
                if selected_tests:
                    selected_count = _count_selected_test_methods(selected_tests)
                    lines.append(f"- **Selected Tests**: {selected_count}")
                    lines.append("```")
                    for t in selected_tests:
                        lines.append(t)
                    lines.append("```")
                if test.get('error_message'):
                    lines.append(f"- **Test Error**: {test.get('error_message')}")
                if test.get('failed_tests'):
                    lines.append("- **Failed Tests**:")
                    lines.append("```")
                    for ft in test.get('failed_tests', []):
                        if isinstance(ft, str):
                            lines.append(ft)
                        else:
                            lines.append(ft.get('full_name', '') or f"{ft.get('class','')}.{ft.get('method','')}")
                    lines.append("```")

                if cov:
                    lines.append(f"- **Changed-Line Coverage**: {_cov_method(cov)}")
                    lines.append(f"- **Changed-Branch Coverage**: {_cov_branch(cov)}")

                if build.get('stdout'):
                    lines.append("- **Build Output (tail)**:")
                    lines.append("```")
                    lines.append(build.get('stdout', '').strip())
                    lines.append("```")
                if build.get('stderr'):
                    lines.append("- **Build Error Output (tail)**:")
                    lines.append("```")
                    lines.append(build.get('stderr', '').strip())
                    lines.append("```")
                if test.get('stdout'):
                    lines.append("- **Test Output (tail)**:")
                    lines.append("```")
                    lines.append(test.get('stdout', '').strip())
                    lines.append("```")
                if test.get('stderr'):
                    lines.append("- **Test Error Output (tail)**:")
                    lines.append("```")
                    lines.append(test.get('stderr', '').strip())
                    lines.append("```")

                lines.append("")

            _emit_version_section("V-1", "Parent commit (baseline)", v1, basic.get('parent_hash'))
            _emit_version_section("V-0.5", "Parent + source-only patch", v05, basic.get('parent_hash'))
            _emit_version_section("T-0.5", "Parent + test-only patch", t05, basic.get('parent_hash'))
            _emit_version_section("V0", "Full commit (source + tests)", v0, basic.get('commit_hash'))

            change_stats = diff_info.get('change_stats', {})
            full_stats = change_stats.get('full', {})
            source_stats = change_stats.get('source', {})
            test_stats = change_stats.get('test', {})

            lines.append("## Change Summary\n")
            lines.append(f"- **Total lines**: +{full_stats.get('total_lines_added', 0)} / -{full_stats.get('total_lines_removed', 0)}")
            lines.append(f"- **Source files**: +{source_stats.get('total_lines_added', 0)} / -{source_stats.get('total_lines_removed', 0)}")
            lines.append(f"- **Test files**: +{test_stats.get('total_lines_added', 0)} / -{test_stats.get('total_lines_removed', 0)}")
            lines.append("")

            lines.append("### File Changes\n")
            lines.append("| File | Type | +Lines | -Lines |")
            lines.append("|------|------|--------|--------|")

            source_paths = {f.get('path') for f in file_changes.get('source_files', [])}
            test_paths = {f.get('path') for f in file_changes.get('test_files', [])}
            for f in full_stats.get('files', []):
                path = f.get('path')
                if path in source_paths:
                    ftype = "source"
                elif path in test_paths:
                    ftype = "test"
                else:
                    ftype = "other"
                lines.append(f"| {path} | {ftype} | {f.get('lines_added', 0)} | {f.get('lines_removed', 0)} |")
            lines.append("")

            v05_line_details = {}
            v0_line_details = {}
            v05_cov = v05.get('coverage', {}).get('method_line_coverage', {})
            v0_cov = v0.get('coverage', {}).get('method_line_coverage', {})
            for d in v05_cov.get('details', []) or []:
                v05_line_details[d.get('method')] = d.get('coverage_ratio', 0)
            for d in v0_cov.get('details', []) or []:
                v0_line_details[d.get('method')] = d.get('coverage_ratio', 0)

            lines.append("### Changed Methods (Source)\n")
            lines.append("| Method | File | +Lines | -Lines | \u0394Lines | V-0.5 Line Cov | V0 Line Cov | \u0394Coverage |")
            lines.append("|--------|------|--------|--------|--------|----------------|--------------|-----------|")

            changed_source = method_changes.get('source_methods', [])
            stats_source = method_change_stats.get('source', []) if method_change_stats else []
            stats_map = {}
            for s in stats_source:
                key = f"{s.get('package')}.{s.get('class')}.{s.get('method')}".strip('.')
                stats_map[key] = s

            for m in changed_source:
                key = f"{m.get('package')}.{m.get('class')}.{m.get('method')}".strip('.')
                s = stats_map.get(key, {})
                added = s.get('added_lines', 0)
                removed = s.get('removed_lines', 0)
                total = s.get('total_changed_lines', added + removed)
                full_name = key
                v05_ratio = v05_line_details.get(full_name, 0)
                v0_ratio = v0_line_details.get(full_name, 0)
                delta = v0_ratio - v05_ratio
                lines.append(
                    f"| {full_name} | {m.get('file','')} | {added} | {removed} | {total} | "
                    f"{v05_ratio:.4f} | {v0_ratio:.4f} | {delta:+.4f} |"
                )
            lines.append("")

            if method_change_stats and method_change_stats.get('test'):
                lines.append("### Changed Methods (Tests)\n")
                lines.append("| Method | File | +Lines | -Lines | \u0394Lines |")
                lines.append("|--------|------|--------|--------|--------|")
                for s in method_change_stats.get('test', []):
                    key = f"{s.get('package')}.{s.get('class')}.{s.get('method')}".strip('.')
                    lines.append(
                        f"| {key} | {s.get('file','')} | {s.get('added_lines',0)} | {s.get('removed_lines',0)} | {s.get('total_changed_lines',0)} |"
                    )
                lines.append("")

            selected_tests = []
            for data in (v1, v05, t05, v0):
                selected_tests.extend(data.get('test', {}).get('selected_tests', []) or [])
            selected_tests = sorted(set(selected_tests))
            if selected_tests:
                lines.append("### Selected Tests\n")
                for test in selected_tests:
                    lines.append(f"- `{test}`")
                lines.append("")

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

        except Exception as e:
            logger.error(f"Failed to generate commit Markdown: {e}")

    def generate_global_summary(self, project_results: List['ProjectAnalysisResult'],
                               output_dir: str):
        """Generate global summary report"""
        os.makedirs(output_dir, exist_ok=True)

        # Aggregate statistics
        summary = {
            'total_projects': len(project_results),
            'analysis_date': datetime.now().isoformat(),
            'projects': []
        }

        total_qualified = 0
        total_type1 = 0
        total_type2 = 0
        total_type3 = 0

        for result in project_results:
            project_info = result.project_info
            type_stats = result.type_statistics

            qualified_count = len(result.qualified_commits)
            type1_count = type_stats.get('type1_execution_error', {}).get('count', 0)
            type2_count = type_stats.get('type2_coverage_decrease', {}).get('count', 0)
            type3_count = type_stats.get('type3_adaptive_change', {}).get('count', 0)

            summary['projects'].append({
                'name': project_info.get('name'),
                'qualified_commits': qualified_count,
                'type1_count': type1_count,
                'type2_count': type2_count,
                'type3_count': type3_count
            })

            total_qualified += qualified_count
            total_type1 += type1_count
            total_type2 += type2_count
            total_type3 += type3_count

        summary['totals'] = {
            'qualified_commits': total_qualified,
            'type1_count': total_type1,
            'type2_count': total_type2,
            'type3_count': total_type3
        }

        # Save JSON
        json_path = os.path.join(output_dir, 'all_projects_stats.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        # Generate Markdown report
        md_content = self._build_global_markdown(summary, project_results)
        md_path = os.path.join(output_dir, 'analysis_report.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"Global summary report generated: {output_dir}")

    def _build_global_markdown(self, summary: dict, results: List['ProjectAnalysisResult']) -> str:
        """Build global Markdown content"""
        lines = []

        lines.append("# TUBench Global Analysis Report\n")
        lines.append(f"**Analysis Date**: {summary['analysis_date'][:10]}")
        lines.append(f"**Project Count**: {summary['total_projects']}")
        lines.append("")

        # Overall statistics
        lines.append("## Overall Statistics\n")
        totals = summary.get('totals', {})
        lines.append(f"- **Total qualified commits**: {totals.get('qualified_commits', 0)}")
        lines.append(f"- **Type1 (execution error)**: {totals.get('type1_count', 0)}")
        lines.append(f"- **Type2 (coverage gap)**: {totals.get('type2_count', 0)}")
        lines.append(f"- **Type3 (adaptive change)**: {totals.get('type3_count', 0)}")
        lines.append("")

        # Per-project breakdown table
        lines.append("## Per-Project Breakdown\n")
        lines.append("| Project | Qualified Commits | Type1 | Type2 | Type3 |")
        lines.append("|---------|-------------------|-------|-------|-------|")

        for proj in summary.get('projects', []):
            lines.append(
                f"| {proj['name']} | {proj['qualified_commits']} | "
                f"{proj['type1_count']} | {proj['type2_count']} | {proj['type3_count']} |"
            )

        # Total row
        lines.append(
            f"| **Total** | **{totals.get('qualified_commits', 0)}** | "
            f"**{totals.get('type1_count', 0)}** | **{totals.get('type2_count', 0)}** | "
            f"**{totals.get('type3_count', 0)}** |"
        )
        lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("*Generated by TUBench Analysis Tool*")

        return '\n'.join(lines)
