"""
Code analysis module - responsible for Java code parsing and method extraction
"""

import javalang
import re
from utils.logger import get_logger
from utils.exceptions import ParseError

logger = get_logger()


class CodeAnalyzer:
    """Java code analyzer"""

    def __init__(self):
        """Initialize the code analyzer"""
        pass

    def parse_java_file(self, file_content):
        """
        Parse a Java file, extracting class and method information

        Args:
            file_content: Java file content

        Returns:
            dict: {'classes': [{'name': str, 'methods': [{'name': str, 'start_line': int, 'end_line': int}]}]}
        """
        try:
            tree = javalang.parse.parse(file_content)
            classes = []

            for path, node in tree.filter(javalang.tree.ClassDeclaration):
                # Build the full class name (including outer classes)
                # path is the path from root to the current node, containing outer class information
                class_name_parts = []
                for path_node in path:
                    if isinstance(path_node, javalang.tree.ClassDeclaration):
                        class_name_parts.append(path_node.name)
                class_name_parts.append(node.name)
                full_class_name = '.'.join(class_name_parts)

                class_info = {
                    'name': full_class_name,
                    'methods': []
                }

                # Extract methods in the class
                for idx, method in enumerate(node.methods):
                    start_line = method.position.line if method.position else 0
                    method_info = {
                        'name': method.name,
                        'start_line': start_line,
                        'parameters': [p.type.name for p in method.parameters] if method.parameters else []
                    }

                    # Estimate the method end line
                    end_line = self._estimate_method_end_line(file_content, start_line)

                    # If the end line cannot be determined, use the start line of the next method as reference
                    if end_line is None:
                        if idx + 1 < len(node.methods) and node.methods[idx + 1].position:
                            # Use the start line of the next method minus 1
                            end_line = node.methods[idx + 1].position.line - 1
                        else:
                            # Last method: use the total number of lines in the file
                            end_line = len(file_content.split('\n'))

                    method_info['end_line'] = end_line
                    class_info['methods'].append(method_info)

                classes.append(class_info)

            return {'classes': classes}

        except Exception as e:
            logger.debug(f"Failed to parse Java file: {e}")
            return {'classes': []}
    
    def _estimate_method_end_line(self, file_content, start_line):
        """
        Estimate the end line number of a method using a state machine to skip
        braces inside strings and comments

        Args:
            file_content: file content
            start_line: method start line number

        Returns:
            int or None: estimated end line number, or None if it cannot be determined
        """
        lines = file_content.split('\n')
        if start_line >= len(lines) or start_line < 1:
            return None

        brace_stack = []  # use a stack to track braces
        found_first_brace = False

        # State tracking
        in_string = False       # inside a string "..."
        in_char = False         # inside a char '...'
        in_single_comment = False  # inside a single-line comment //
        in_multi_comment = False   # inside a multi-line comment /* */
        escape_next = False     # next character is an escape character

        for line_idx in range(start_line - 1, len(lines)):
            line = lines[line_idx]
            in_single_comment = False  # reset single-line comment state for each line

            i = 0
            while i < len(line):
                char = line[i]
                next_char = line[i + 1] if i + 1 < len(line) else ''

                # Handle escape characters
                if escape_next:
                    escape_next = False
                    i += 1
                    continue

                if char == '\\' and (in_string or in_char):
                    escape_next = True
                    i += 1
                    continue

                # Handle end of multi-line comment
                if in_multi_comment:
                    if char == '*' and next_char == '/':
                        in_multi_comment = False
                        i += 2
                        continue
                    i += 1
                    continue

                # Handle single-line comment
                if in_single_comment:
                    i += 1
                    continue

                # Handle string
                if in_string:
                    if char == '"':
                        in_string = False
                    i += 1
                    continue

                # Handle character literal
                if in_char:
                    if char == "'":
                        in_char = False
                    i += 1
                    continue

                # Detect comment start
                if char == '/' and next_char == '/':
                    in_single_comment = True
                    i += 2
                    continue

                if char == '/' and next_char == '*':
                    in_multi_comment = True
                    i += 2
                    continue

                # Detect string/character start
                if char == '"':
                    in_string = True
                    i += 1
                    continue

                if char == "'":
                    in_char = True
                    i += 1
                    continue

                # Handle braces (only count them in code regions)
                if char == '{':
                    brace_stack.append('{')
                    found_first_brace = True
                elif char == '}':
                    if brace_stack:
                        brace_stack.pop()
                    # When the first brace has been found, an empty stack means the method has ended
                    if found_first_brace and len(brace_stack) == 0:
                        return line_idx + 1  # return 1-indexed line number

                i += 1

        # Cannot determine end line; return None for the caller to handle
        return None
    
    def get_methods_in_range(self, classes_info, start_line, end_line):
        """
        Get methods within a specified line range

        Args:
            classes_info: class information dictionary
            start_line: start line
            end_line: end line

        Returns:
            list: list of method information
        """
        methods = []

        for class_info in classes_info.get('classes', []):
            for method in class_info['methods']:
                method_start = method['start_line']
                method_end = method['end_line']

                # Check whether the method overlaps with the specified range
                if self._ranges_overlap(method_start, method_end, start_line, end_line):
                    methods.append({
                        'class': class_info['name'],
                        'method': method['name'],
                        'parameters': method.get('parameters', []),
                        'start_line': method_start,
                        'end_line': method_end
                    })

        return methods

    def _ranges_overlap(self, start1, end1, start2, end2):
        """Check whether two ranges overlap"""
        return not (end1 < start2 or end2 < start1)
    
    def extract_test_methods(self, file_content):
        """
        Extract test methods (methods annotated with @Test)

        Args:
            file_content: Java file content

        Returns:
            list: list of test methods
        """
        try:
            tree = javalang.parse.parse(file_content)
            test_methods = []

            for path, node in tree.filter(javalang.tree.ClassDeclaration):
                class_name = node.name

                for method in node.methods:
                    # Check whether the method has an @Test annotation
                    if method.annotations:
                        for annotation in method.annotations:
                            if annotation.name == 'Test':
                                test_methods.append({
                                    'class': class_name,
                                    'method': method.name,
                                    'start_line': method.position.line if method.position else 0
                                })
                                break

            return test_methods

        except Exception as e:
            logger.debug(f"Failed to extract test methods: {e}")
            return []
    
    def get_package_name(self, file_content):
        """
        Get the package name of a Java file

        Args:
            file_content: Java file content

        Returns:
            str: package name
        """
        try:
            tree = javalang.parse.parse(file_content)
            return tree.package.name if tree.package else ""
        except:
            return ""

    def get_class_full_name(self, file_path, file_content):
        """
        Get the fully qualified class name

        Args:
            file_path: file path
            file_content: file content

        Returns:
            str: fully qualified class name (e.g. com.example.MyClass)
        """
        package = self.get_package_name(file_content)
        class_name = file_path.split('/')[-1].replace('.java', '')

        if package:
            return f"{package}.{class_name}"
        return class_name
