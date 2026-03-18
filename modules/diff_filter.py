"""
Diff过滤器 - 负责从完整diff中过滤掉测试代码的变更
"""

import re
from config import Config
from utils.logger import get_logger

logger = get_logger()


class DiffFilter:
    """Diff过滤器 - 分离源代码变更和测试代码变更"""
    
    def __init__(self):
        """初始化Diff过滤器"""
        pass
    
    def filter_test_changes(self, diff_text):
        """
        从完整diff中过滤掉测试文件的变更，只保留源代码变更
        
        Args:
            diff_text: 完整的diff文本
            
        Returns:
            tuple: (filtered_diff: str, test_diff: str, stats: dict)
                - filtered_diff: 只包含源代码变更的diff
                - test_diff: 只包含测试代码变更的diff
                - stats: 统计信息
        """
        try:
            if not diff_text:
                return "", "", {"source_files": 0, "test_files": 0}
            
            # 按文件分割diff
            file_diffs = self._split_diff_by_file(diff_text)
            
            source_diffs = []
            test_diffs = []
            
            for file_diff, file_path in file_diffs:
                # 判断文件类型
                if self._is_test_file(file_path):
                    test_diffs.append(file_diff)
                else:
                    source_diffs.append(file_diff)
            
            # 合并diff文本
            filtered_diff = "\n".join(source_diffs)
            test_diff = "\n".join(test_diffs)
            
            stats = {
                "source_files": len(source_diffs),
                "test_files": len(test_diffs),
                "filtered": len(test_diffs) > 0
            }
            
            logger.debug(f"Diff过滤: {stats['source_files']} 源文件, {stats['test_files']} 测试文件")
            
            return filtered_diff, test_diff, stats
        
        except Exception as e:
            logger.error(f"过滤diff失败: {e}")
            return "", "", {"source_files": 0, "test_files": 0, "error": str(e)}
    
    def _is_test_file(self, file_path):
        """判断文件是否为测试文件"""
        return any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS)
    
    def _split_diff_by_file(self, diff_text):
        """
        按文件分割diff文本

        Args:
            diff_text: 完整的diff文本

        Returns:
            list: [(file_diff, file_path), ...]
        """
        file_diffs = []

        # 按行处理，只在行首匹配 "diff --git"
        # 这样可以避免误匹配 diff 内容中包含的 "diff --git" 字符串
        lines = diff_text.split('\n')

        current_diff_lines = []
        current_path = None

        for line in lines:
            # 检查是否是新文件的开始（必须在行首）
            if line.startswith('diff --git '):
                # 保存前一个文件的diff
                if current_diff_lines and current_path:
                    file_diffs.append(('\n'.join(current_diff_lines), current_path))

                # 开始新的文件diff
                current_diff_lines = [line]

                # 提取文件路径
                match = re.search(r'diff --git a/(.*?) b/', line)
                if match:
                    current_path = match.group(1)
                else:
                    current_path = None
            else:
                # 添加到当前文件的diff
                current_diff_lines.append(line)

        # 保存最后一个文件的diff
        if current_diff_lines and current_path:
            file_diffs.append(('\n'.join(current_diff_lines), current_path))

        return file_diffs
    
    def extract_test_changes_info(self, test_diff):
        """
        从测试diff中提取变更信息
        
        Args:
            test_diff: 测试代码的diff
            
        Returns:
            dict: 测试变更信息
        """
        return self.extract_changes_info(test_diff, label="测试")

    def extract_changes_info(self, diff_text, label=""):
        """
        从diff中提取变更信息（通用）
        
        Args:
            diff_text: diff文本
            label: 日志标签
            
        Returns:
            dict: 变更信息
        """
        try:
            if not diff_text:
                return {"files": [], "total_lines_added": 0, "total_lines_removed": 0}
            
            file_diffs = self._split_diff_by_file(diff_text)
            files_info = []
            total_added = 0
            total_removed = 0
            
            for file_diff, file_path in file_diffs:
                # 统计添加和删除的行数
                added = len([
                    line for line in file_diff.split('\n')
                    if line.startswith('+') and not line.startswith('+++')
                ])
                removed = len([
                    line for line in file_diff.split('\n')
                    if line.startswith('-') and not line.startswith('---')
                ])
                
                # 检测新文件和删除文件
                is_new = 'new file mode' in file_diff
                is_deleted = 'deleted file mode' in file_diff
                
                file_info = {
                    "path": file_path,
                    "lines_added": added,
                    "lines_removed": removed,
                    "is_new": is_new,
                    "is_deleted": is_deleted
                }
                files_info.append(file_info)
                total_added += added
                total_removed += removed
            
            return {
                "files": files_info,
                "total_lines_added": total_added,
                "total_lines_removed": total_removed
            }
        
        except Exception as e:
            prefix = f"{label}变更" if label else "变更"
            logger.error(f"提取{prefix}信息失败: {e}")
            return {"files": [], "total_lines_added": 0, "total_lines_removed": 0}
