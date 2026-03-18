"""
覆盖率分析模块 - 负责解析JaCoCo报告并分析覆盖情况
"""

import os
import xml.etree.ElementTree as ET
from utils.logger import get_logger
from utils.exceptions import CoverageError

logger = get_logger()


class CoverageAnalyzer:
    """覆盖率分析器"""
    
    def __init__(self):
        """初始化覆盖率分析器"""
        pass
    
    def parse_jacoco_report(self, report_path):
        """
        解析JaCoCo XML报告
        
        Args:
            report_path: JaCoCo报告文件路径
            
        Returns:
            dict: 覆盖率数据 {'classes': {'pkg.ClassName': {covered_lines: set()}}}
        """
        try:
            if not os.path.exists(report_path):
                logger.error(f"JaCoCo报告不存在: {report_path}")
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
            
            # 遍历所有package
            for package in root.findall('.//package'):
                package_name = package.get('name', '').replace('/', '.')
                
                # 遍历package中的sourcefile
                for sourcefile in package.findall('sourcefile'):
                    source_name = sourcefile.get('name', '')
                    # 尝试推断类名 (简化处理：假设类名与文件名一致)
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
                        
                        # 同时也尝试匹配可能的内部类或其他类名
                        # 在JaCoCo中，class元素和sourcefile元素是兄弟，但我们这里主要关心行覆盖
                        # 为了兼容性，我们也可以遍历class元素来获取更精确的类名映射，但行信息只在sourcefile里
            
            logger.debug(f"成功解析JaCoCo报告: {report_path}")
            return coverage_data
        
        except Exception as e:
            logger.error(f"解析JaCoCo报告失败 [{report_path}]: {e}")
            return None

    def analyze_test_coverage_for_changes(self, coverage_data, changed_test_methods, 
                                          changed_source_methods):
        """
        分析变更的被测方法的覆盖情况
        
        Args:
            coverage_data: 覆盖率数据
            changed_test_methods: 变更的测试方法列表 (仅用于统计，不用于关联)
            changed_source_methods: 变更的被测方法列表
            
        Returns:
            dict: 覆盖率统计
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
            
            # 查找该类的覆盖信息
            class_cov = classes_coverage.get(full_class_name)
            
            # 如果精确匹配失败，尝试模糊匹配（处理内部类情况）
            if not class_cov:
                class_cov = self._fuzzy_match_class(classes_coverage, method.get('class', ''), full_class_name)
            
            # 检查方法范围内是否有被覆盖的行
            if class_cov:
                covered_lines = class_cov['covered_lines']
                # 只要有一行被覆盖，我们就算该方法被覆盖了
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
        
        # 计算覆盖率：被覆盖的变更方法 / 总变更方法
        coverage_ratio = covered_count / total_methods if total_methods > 0 else 0.0
        
        return {
            'total_methods': total_methods,
            'covered_methods': covered_count,
            'coverage_ratio': coverage_ratio,
            'details': details
        }

    def analyze_changed_methods_line_coverage(self, coverage_data, changed_source_methods):
        """
        计算变更方法的行覆盖率（覆盖行数 / 总行数）

        Args:
            coverage_data: 覆盖率数据
            changed_source_methods: 变更的被测方法列表

        Returns:
            dict: 行覆盖率统计
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
        计算变更方法的分支覆盖率（覆盖分支数 / 总分支数）
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
        模糊匹配类名，处理内部类情况
        
        策略：
        1. 精确匹配（将 . 转换为 $ 处理内部类）
        2. 查找以 .ClassName 结尾的 key
        3. 查找以 $ClassName 结尾的 key（内部类，ClassName 作为内部类名）
        4. 查找包含 ClassName$ 的 key（内部类模式，ClassName 作为外部类）
        5. 查找源文件名匹配的 key
        
        Args:
            classes_coverage: 覆盖率数据字典
            class_name: 简单类名（可能包含 . 如 CSVParser.Builder）
            full_class_name: 完整类名（如 org.apache.commons.csv.CSVParser.Builder）
            
        Returns:
            dict or None: 匹配的覆盖信息，未找到返回None
        """
        if not class_name:
            return None
        
        # 策略0: 如果类名包含 .（内部类），转换为 $ 格式尝试精确匹配
        if '.' in class_name:
            # full_class_name: org.apache.commons.csv.CSVParser.Builder
            # 需要转换为: org.apache.commons.csv.CSVParser$Builder
            parts = full_class_name.rsplit('.', 1)
            if len(parts) == 2:
                # 找到最后一个类名部分，检查它是否也在前面的部分中
                # 例如 CSVParser.Builder -> 需要找 CSVParser$Builder
                inner_class_name = class_name.replace('.', '$')
                package = full_class_name[:full_class_name.rfind(class_name)].rstrip('.')
                jacoco_class_name = f"{package}.{inner_class_name}" if package else inner_class_name
                
                if jacoco_class_name in classes_coverage:
                    logger.debug(f"内部类转换匹配: {full_class_name} -> {jacoco_class_name}")
                    return classes_coverage[jacoco_class_name]
            
            # 策略0b: JaCoCo sourcefile模式下内部类覆盖数据归属于外部类的源文件
            # 例如 CSVParser.CSVRecordIterator -> 尝试 org.apache.commons.csv.CSVParser
            outer_class = class_name.split('.')[0]  # "CSVParser"
            package_prefix = full_class_name[:full_class_name.find(class_name)].rstrip('.')
            outer_full_name = f"{package_prefix}.{outer_class}" if package_prefix else outer_class
            if outer_full_name in classes_coverage:
                logger.debug(f"内部类使用外部类sourcefile匹配: {full_class_name} -> {outer_full_name}")
                return classes_coverage[outer_full_name]
        
        # 策略1: 查找以 .ClassName 结尾的 key（处理简单类名）
        simple_class_name = class_name.split('.')[-1] if '.' in class_name else class_name
        suffix = f".{simple_class_name}"
        for key, value in classes_coverage.items():
            if key.endswith(suffix):
                logger.debug(f"模糊匹配成功: {full_class_name} -> {key}")
                return value
        
        # 策略2: 查找以 $ClassName 结尾的 key（内部类，ClassName 作为内部类名）
        inner_suffix = f"${simple_class_name}"
        for key, value in classes_coverage.items():
            if key.endswith(inner_suffix):
                logger.debug(f"内部类后缀匹配: {full_class_name} -> {key}")
                return value
        
        # 策略3: 查找包含 ClassName$ 的 key（内部类模式，ClassName 作为外部类）
        inner_class_pattern = f"{simple_class_name}$"
        for key, value in classes_coverage.items():
            if inner_class_pattern in key:
                logger.debug(f"内部类匹配: {full_class_name} -> {key}")
                return value
        
        # 策略4: 通过源文件名匹配
        source_file = f"{simple_class_name}.java"
        for key, value in classes_coverage.items():
            if value.get('source_file') == source_file:
                logger.debug(f"源文件匹配: {full_class_name} -> {key}")
                return value
        
        return None
