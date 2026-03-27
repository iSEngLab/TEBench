"""
Coverage analysis module - responsible for parsing JaCoCo reports and analyzing coverage
"""

import os
import xml.etree.ElementTree as ET
from utils.logger import get_logger
from utils.exceptions import CoverageError

logger = get_logger()


class CoverageAnalyzer:
    """Coverage analyzer"""

    def __init__(self):
        """Initialize the coverage analyzer"""
        pass

    def parse_jacoco_report(self, report_path):
        """
        Parse a JaCoCo XML report

        Args:
            report_path: path to the JaCoCo report file

        Returns:
            dict: coverage data {'classes': {'pkg.ClassName': {covered_lines: set()}}}
        """
        try:
            if not os.path.exists(report_path):
                logger.error(f"JaCoCo report does not exist: {report_path}")
                return None
            
            tree = ET.parse(report_path)
            root = tree.getroot()
            
            coverage_data = {
                'classes': {},
                'summary': {}
            }

            # Overall coverage summary from report-level counters (preferred)
            line_counter = None
            for counter in root.findall('counter'):
                if counter.get('type') == 'LINE':
                    line_counter = counter
                    break

            if line_counter is not None:
                try:
                    missed = int(line_counter.get('missed', 0))
                    covered = int(line_counter.get('covered', 0))
                    coverage_data['summary']['line'] = {
                        'missed': missed,
                        'covered': covered,
                        'total': missed + covered
                    }
                except Exception:
                    # Keep summary empty if parsing fails
                    pass
            
            # Iterate over all packages
            for package in root.findall('.//package'):
                package_name = package.get('name', '').replace('/', '.')

                # Iterate over sourcefiles in the package
                for sourcefile in package.findall('sourcefile'):
                    source_name = sourcefile.get('name', '')
                    # Attempt to infer the class name (simplified: assume class name matches file name)
                    class_simple_name = source_name.replace('.java', '')
                    full_class_name = f"{package_name}.{class_simple_name}"

                    covered_lines = set()
                    line_status = {}
                    branch_status = {}
                    instrumented_lines = set()
                    for line in sourcefile.findall('line'):
                        nr = int(line.get('nr', 0))
                        ci = int(line.get('ci', 0))
                        mi = int(line.get('mi', 0))
                        cb = int(line.get('cb', 0))
                        mb = int(line.get('mb', 0))
                        if ci + mi == 0:
                            continue
                        instrumented_lines.add(nr)
                        is_covered = ci > 0
                        line_status[nr] = is_covered
                        if cb + mb > 0:
                            branch_status[nr] = {
                                'covered': cb,
                                'total': cb + mb
                            }
                        if is_covered:
                            covered_lines.add(nr)

                    # Keep class coverage even when no line is covered.
                    # Otherwise, changed methods in uncovered classes are treated as
                    # "class not found" instead of explicit zero coverage.
                    if line_status or branch_status or instrumented_lines:
                        coverage_data['classes'][full_class_name] = {
                            'source_file': source_name,
                            'covered_lines': covered_lines,
                            'line_status': line_status,
                            'branch_status': branch_status,
                            'instrumented_lines': instrumented_lines
                        }

                        # Also attempt to match possible inner classes or other class names.
                        # In JaCoCo, class elements and sourcefile elements are siblings, but
                        # here we primarily care about line coverage.
                        # For compatibility, we could also iterate class elements for more precise
                        # class name mapping, but line information is only in sourcefiles.

            logger.debug(f"Successfully parsed JaCoCo report: {report_path}")
            return coverage_data

        except Exception as e:
            logger.error(f"Failed to parse JaCoCo report [{report_path}]: {e}")
            return None

    def analyze_test_coverage_for_changes(self, coverage_data, changed_test_methods,
                                          changed_source_methods):
        """
        Analyze the coverage of changed methods under test

        Args:
            coverage_data: coverage data
            changed_test_methods: list of changed test methods (used for statistics only, not for association)
            changed_source_methods: list of changed methods under test

        Returns:
            dict: coverage statistics
        """
        if not coverage_data or not changed_source_methods:
            return {
                'total_methods': 0,
                'covered_methods': 0,
                'coverage_ratio': 0.0,
                'details': []
            }

        total_methods = len(changed_source_methods)
        covered_count = 0
        details = []

        classes_coverage = coverage_data.get('classes', {})

        for method in changed_source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)

            is_covered = False

            # Look up the coverage information for this class
            class_cov = classes_coverage.get(full_class_name)

            # If exact match fails, try fuzzy matching (to handle inner classes)
            if not class_cov:
                class_cov = self._fuzzy_match_class(classes_coverage, method.get('class', ''), full_class_name)

            # Check whether any line in the method range is covered
            if class_cov:
                covered_lines = class_cov['covered_lines']
                # If at least one line is covered, we consider the method covered
                for line_num in range(start_line, end_line + 1):
                    if line_num in covered_lines:
                        is_covered = True
                        break

            if is_covered:
                covered_count += 1

            details.append({
                'method': f"{full_class_name}.{method.get('method', '')}",
                'covered': is_covered
            })

        # Calculate coverage ratio: covered changed methods / total changed methods
        coverage_ratio = covered_count / total_methods if total_methods > 0 else 0.0

        return {
            'total_methods': total_methods,
            'covered_methods': covered_count,
            'coverage_ratio': coverage_ratio,
            'details': details
        }

    def analyze_changed_methods_line_coverage(self, coverage_data, changed_source_methods):
        """
        Calculate the line coverage ratio of changed methods (covered lines / total lines)

        Args:
            coverage_data: coverage data
            changed_source_methods: list of changed methods under test

        Returns:
            dict: line coverage statistics
        """
        if not coverage_data or not changed_source_methods:
            return {
                'total_methods': 0,
                'methods_with_data': 0,
                'covered_lines': 0,
                'total_lines': 0,
                'coverage_ratio': 0.0,
                'details': []
            }

        total_lines = 0
        covered_lines = 0
        methods_with_data = 0
        details = []

        classes_coverage = coverage_data.get('classes', {})

        for method in changed_source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)

            class_cov = classes_coverage.get(full_class_name)
            if not class_cov:
                class_cov = self._fuzzy_match_class(classes_coverage, method.get('class', ''), full_class_name)

            method_total = 0
            method_covered = 0

            if class_cov:
                line_status = class_cov.get('line_status', {})
                if line_status:
                    for line_num in range(start_line, end_line + 1):
                        if line_num in line_status:
                            method_total += 1
                            if line_status.get(line_num):
                                method_covered += 1

            if method_total > 0:
                methods_with_data += 1

            total_lines += method_total
            covered_lines += method_covered

            details.append({
                'method': f"{full_class_name}.{method.get('method', '')}",
                'covered_lines': method_covered,
                'total_lines': method_total,
                'coverage_ratio': (method_covered / method_total) if method_total > 0 else 0.0
            })

        coverage_ratio = covered_lines / total_lines if total_lines > 0 else 0.0

        return {
            'total_methods': len(changed_source_methods),
            'methods_with_data': methods_with_data,
            'covered_lines': covered_lines,
            'total_lines': total_lines,
            'coverage_ratio': coverage_ratio,
            'details': details
        }

    def analyze_changed_methods_branch_coverage(self, coverage_data, changed_source_methods):
        """
        Calculate the branch coverage ratio of changed methods (covered branches / total branches)
        """
        if not coverage_data or not changed_source_methods:
            return {
                'total_methods': 0,
                'methods_with_data': 0,
                'covered_branches': 0,
                'total_branches': 0,
                'coverage_ratio': 0.0,
                'details': []
            }

        total_branches = 0
        covered_branches = 0
        methods_with_data = 0
        details = []

        classes_coverage = coverage_data.get('classes', {})

        for method in changed_source_methods:
            full_class_name = f"{method.get('package', '')}.{method.get('class', '')}"
            start_line = method.get('start_line', 0)
            end_line = method.get('end_line', 0)

            class_cov = classes_coverage.get(full_class_name)
            if not class_cov:
                class_cov = self._fuzzy_match_class(classes_coverage, method.get('class', ''), full_class_name)

            method_total = 0
            method_covered = 0

            if class_cov:
                branch_status = class_cov.get('branch_status', {})
                if branch_status:
                    for line_num in range(start_line, end_line + 1):
                        if line_num in branch_status:
                            info = branch_status[line_num]
                            method_total += info.get('total', 0)
                            method_covered += info.get('covered', 0)

            if method_total > 0:
                methods_with_data += 1

            total_branches += method_total
            covered_branches += method_covered

            details.append({
                'method': f"{full_class_name}.{method.get('method', '')}",
                'covered_branches': method_covered,
                'total_branches': method_total,
                'coverage_ratio': (method_covered / method_total) if method_total > 0 else 0.0
            })

        coverage_ratio = covered_branches / total_branches if total_branches > 0 else 0.0

        return {
            'total_methods': len(changed_source_methods),
            'methods_with_data': methods_with_data,
            'covered_branches': covered_branches,
            'total_branches': total_branches,
            'coverage_ratio': coverage_ratio,
            'details': details
        }
    
    def _fuzzy_match_class(self, classes_coverage, class_name, full_class_name):
        """
        Fuzzy match a class name, handling inner class cases

        Strategy:
        1. Exact match (convert . to $ for inner classes)
        2. Find keys ending with .ClassName
        3. Find keys ending with $ClassName (inner class, ClassName as inner class name)
        4. Find keys containing ClassName$ (inner class pattern, ClassName as outer class)
        5. Find keys matching by source file name

        Args:
            classes_coverage: coverage data dictionary
            class_name: simple class name (may contain . like CSVParser.Builder)
            full_class_name: fully qualified class name (e.g. org.apache.commons.csv.CSVParser.Builder)

        Returns:
            dict or None: matching coverage information, or None if not found
        """
        if not class_name:
            return None

        # Strategy 0: if class name contains . (inner class), convert to $ format and try exact match
        if '.' in class_name:
            # full_class_name: org.apache.commons.csv.CSVParser.Builder
            # need to convert to: org.apache.commons.csv.CSVParser$Builder
            parts = full_class_name.rsplit('.', 1)
            if len(parts) == 2:
                # Find the last class name part and check if it also appears in the preceding part
                # e.g. CSVParser.Builder -> need to find CSVParser$Builder
                inner_class_name = class_name.replace('.', '$')
                package = full_class_name[:full_class_name.rfind(class_name)].rstrip('.')
                jacoco_class_name = f"{package}.{inner_class_name}" if package else inner_class_name

                if jacoco_class_name in classes_coverage:
                    logger.debug(f"Inner class conversion match: {full_class_name} -> {jacoco_class_name}")
                    return classes_coverage[jacoco_class_name]

            # Strategy 0b: in JaCoCo sourcefile mode, inner class coverage data belongs to the outer class sourcefile
            # e.g. CSVParser.CSVRecordIterator -> try org.apache.commons.csv.CSVParser
            outer_class = class_name.split('.')[0]  # "CSVParser"
            package_prefix = full_class_name[:full_class_name.find(class_name)].rstrip('.')
            outer_full_name = f"{package_prefix}.{outer_class}" if package_prefix else outer_class
            if outer_full_name in classes_coverage:
                logger.debug(f"Inner class matched via outer class sourcefile: {full_class_name} -> {outer_full_name}")
                return classes_coverage[outer_full_name]

        # Strategy 1: find keys ending with .ClassName (handle simple class names)
        simple_class_name = class_name.split('.')[-1] if '.' in class_name else class_name
        suffix = f".{simple_class_name}"
        for key, value in classes_coverage.items():
            if key.endswith(suffix):
                logger.debug(f"Fuzzy match successful: {full_class_name} -> {key}")
                return value

        # Strategy 2: find keys ending with $ClassName (inner class, ClassName as inner class name)
        inner_suffix = f"${simple_class_name}"
        for key, value in classes_coverage.items():
            if key.endswith(inner_suffix):
                logger.debug(f"Inner class suffix match: {full_class_name} -> {key}")
                return value

        # Strategy 3: find keys containing ClassName$ (inner class pattern, ClassName as outer class)
        inner_class_pattern = f"{simple_class_name}$"
        for key, value in classes_coverage.items():
            if inner_class_pattern in key:
                logger.debug(f"Inner class match: {full_class_name} -> {key}")
                return value

        # Strategy 4: match by source file name
        source_file = f"{simple_class_name}.java"
        for key, value in classes_coverage.items():
            if value.get('source_file') == source_file:
                logger.debug(f"Source file match: {full_class_name} -> {key}")
                return value

        return None
