"""
改动量计算器 - 计算测试修改的改动量（基于Token Jaccard相似度）
"""

import re
from typing import Dict, Any, List, Optional
from collections import Counter

from git import Repo

from utils.logger import get_logger

logger = get_logger()


class ModificationEffortCalculator:
    """改动量计算器 - 基于Token Jaccard相似度计算改动量"""

    def __init__(self, repo_path: str):
        """
        初始化改动量计算器

        Args:
            repo_path: 仓库路径
        """
        self.repo_path = repo_path
        self.repo = Repo(repo_path)

    def calculate(self,
                  common_methods: List[Dict],
                  user_commit: str,
                  gt_commit: str) -> Dict[str, Any]:
        """
        计算改动量

        Args:
            common_methods: 共同变更的方法列表
            user_commit: 用户commit hash
            gt_commit: GT commit hash

        Returns:
            dict: {
                'method_details': [...],
                'average_jaccard': float,
                'average_effort': float,
                'total_methods': int,
                'error': str
            }
        """
        result = {
            'method_details': [],
            'average_jaccard': 0.0,
            'average_effort': 1.0,
            'total_methods': len(common_methods),
            'error': None
        }

        if not common_methods:
            result['error'] = "没有共同变更的方法"
            return result

        try:
            jaccard_sum = 0.0
            valid_count = 0

            for method in common_methods:
                method_result = self._calculate_method_jaccard(
                    method, user_commit, gt_commit
                )

                if method_result:
                    result['method_details'].append(method_result)
                    if method_result.get('jaccard_similarity') is not None:
                        jaccard_sum += method_result['jaccard_similarity']
                        valid_count += 1

            if valid_count > 0:
                result['average_jaccard'] = jaccard_sum / valid_count
                result['average_effort'] = 1 - result['average_jaccard']

            logger.debug(f"改动量计算: {valid_count}/{len(common_methods)} 方法, "
                        f"平均Jaccard={result['average_jaccard']:.2%}")

        except Exception as e:
            logger.error(f"计算改动量失败: {e}")
            result['error'] = str(e)

        return result

    def _calculate_method_jaccard(self,
                                   method: Dict,
                                   user_commit: str,
                                   gt_commit: str) -> Optional[Dict]:
        """计算单个方法的Jaccard相似度"""
        try:
            file_path = method.get('file')
            class_name = method.get('class')
            method_name = method.get('method')

            # 获取用户版本的方法代码
            user_code = self._extract_method_code(
                user_commit, file_path,
                method.get('user_start_line'),
                method.get('user_end_line')
            )

            # 获取GT版本的方法代码
            gt_code = self._extract_method_code(
                gt_commit, file_path,
                method.get('gt_start_line'),
                method.get('gt_end_line')
            )

            if not user_code or not gt_code:
                return {
                    'class': class_name,
                    'method': method_name,
                    'file': file_path,
                    'error': 'Could not extract method code',
                    'jaccard_similarity': None,
                    'modification_effort': None
                }

            # Tokenize
            user_tokens = self._tokenize(user_code)
            gt_tokens = self._tokenize(gt_code)

            # 计算Jaccard
            jaccard = self._jaccard_similarity(user_tokens, gt_tokens)

            return {
                'class': class_name,
                'method': method_name,
                'file': file_path,
                'user_tokens_count': len(user_tokens),
                'gt_tokens_count': len(gt_tokens),
                'common_tokens_count': len(set(user_tokens) & set(gt_tokens)),
                'jaccard_similarity': jaccard,
                'modification_effort': 1 - jaccard
            }

        except Exception as e:
            logger.debug(f"计算方法Jaccard失败: {e}")
            return None

    def _extract_method_code(self,
                              commit_hash: str,
                              file_path: str,
                              start_line: int,
                              end_line: int) -> Optional[str]:
        """从指定commit中提取方法代码"""
        try:
            if not start_line or not end_line:
                return None

            commit = self.repo.commit(commit_hash)
            blob = commit.tree / file_path
            content = blob.data_stream.read().decode('utf-8', errors='ignore')

            lines = content.split('\n')
            if start_line < 1 or end_line > len(lines):
                return None

            return '\n'.join(lines[start_line - 1:end_line])

        except Exception as e:
            logger.debug(f"提取方法代码失败: {e}")
            return None

    def _tokenize(self, code: str) -> List[str]:
        """
        将Java代码转换为token列表

        Args:
            code: Java代码

        Returns:
            list: token列表
        """
        try:
            # 尝试使用javalang进行tokenize
            import javalang
            tokens = list(javalang.tokenizer.tokenize(code))
            return [t.value for t in tokens]

        except Exception:
            # 如果javalang失败，使用简单的词法分割
            return self._simple_tokenize(code)

    def _simple_tokenize(self, code: str) -> List[str]:
        """简单的词法分割"""
        # 移除注释
        code = self._remove_comments(code)

        # 分割为token
        # 匹配：标识符、数字、字符串、运算符
        pattern = r'[a-zA-Z_][a-zA-Z0-9_]*|[0-9]+(?:\.[0-9]+)?|"[^"]*"|\'[^\']*\'|[^\s\w]'
        tokens = re.findall(pattern, code)

        return tokens

    def _remove_comments(self, code: str) -> str:
        """移除Java注释"""
        # 移除单行注释
        code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
        # 移除多行注释
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        return code

    def _jaccard_similarity(self, tokens1: List[str], tokens2: List[str]) -> float:
        """
        计算Jaccard相似度

        使用multiset（考虑token出现次数）的Jaccard

        Args:
            tokens1: 第一个token列表
            tokens2: 第二个token列表

        Returns:
            float: Jaccard相似度 [0, 1]
        """
        if not tokens1 and not tokens2:
            return 1.0

        if not tokens1 or not tokens2:
            return 0.0

        # 使用Counter计算multiset
        counter1 = Counter(tokens1)
        counter2 = Counter(tokens2)

        # 计算交集（取最小值）
        intersection = sum((counter1 & counter2).values())

        # 计算并集（取最大值）
        union = sum((counter1 | counter2).values())

        if union == 0:
            return 1.0

        return intersection / union

    def calculate_set_jaccard(self, tokens1: List[str], tokens2: List[str]) -> float:
        """
        计算集合Jaccard相似度（不考虑重复）

        Args:
            tokens1: 第一个token列表
            tokens2: 第二个token列表

        Returns:
            float: Jaccard相似度 [0, 1]
        """
        if not tokens1 and not tokens2:
            return 1.0

        if not tokens1 or not tokens2:
            return 0.0

        set1 = set(tokens1)
        set2 = set(tokens2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 1.0

        return intersection / union

    def get_token_diff(self,
                       user_code: str,
                       gt_code: str) -> Dict[str, Any]:
        """
        获取token级别的差异

        Args:
            user_code: 用户代码
            gt_code: GT代码

        Returns:
            dict: token差异信息
        """
        user_tokens = self._tokenize(user_code)
        gt_tokens = self._tokenize(gt_code)

        user_set = set(user_tokens)
        gt_set = set(gt_tokens)

        return {
            'user_only_tokens': list(user_set - gt_set),
            'gt_only_tokens': list(gt_set - user_set),
            'common_tokens': list(user_set & gt_set),
            'user_token_count': len(user_tokens),
            'gt_token_count': len(gt_tokens),
            'jaccard_similarity': self._jaccard_similarity(user_tokens, gt_tokens)
        }
