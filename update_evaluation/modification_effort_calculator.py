"""
Modification effort calculator - calculates test modification effort (based on Token Jaccard similarity)
"""

import re
from typing import Dict, Any, List, Optional
from collections import Counter

from git import Repo

from utils.logger import get_logger

logger = get_logger()


class ModificationEffortCalculator:
    """Modification effort calculator - computes effort based on Token Jaccard similarity"""

    def __init__(self, repo_path: str):
        """
        Initialize the modification effort calculator

        Args:
            repo_path: repository path
        """
        self.repo_path = repo_path
        self.repo = Repo(repo_path)

    def calculate(self,
                  common_methods: List[Dict],
                  user_commit: str,
                  gt_commit: str) -> Dict[str, Any]:
        """
        Calculate modification effort

        Args:
            common_methods: list of methods changed by both user and GT
            user_commit: user commit hash
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
            result['error'] = "No commonly changed methods"
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

            logger.debug(f"Modification effort calculation: {valid_count}/{len(common_methods)} methods, "
                        f"average Jaccard={result['average_jaccard']:.2%}")

        except Exception as e:
            logger.error(f"Failed to calculate modification effort: {e}")
            result['error'] = str(e)

        return result

    def _calculate_method_jaccard(self,
                                   method: Dict,
                                   user_commit: str,
                                   gt_commit: str) -> Optional[Dict]:
        """Calculate Jaccard similarity for a single method"""
        try:
            file_path = method.get('file')
            class_name = method.get('class')
            method_name = method.get('method')

            # Get the user version of the method code
            user_code = self._extract_method_code(
                user_commit, file_path,
                method.get('user_start_line'),
                method.get('user_end_line')
            )

            # Get the GT version of the method code
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

            # Compute Jaccard
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
            logger.debug(f"Failed to calculate method Jaccard: {e}")
            return None

    def _extract_method_code(self,
                              commit_hash: str,
                              file_path: str,
                              start_line: int,
                              end_line: int) -> Optional[str]:
        """Extract method code from a specified commit"""
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
            logger.debug(f"Failed to extract method code: {e}")
            return None

    def _tokenize(self, code: str) -> List[str]:
        """
        Tokenize Java code into a token list

        Args:
            code: Java source code

        Returns:
            list: token list
        """
        try:
            # Attempt to tokenize using javalang
            import javalang
            tokens = list(javalang.tokenizer.tokenize(code))
            return [t.value for t in tokens]

        except Exception:
            # Fall back to simple lexical splitting if javalang fails
            return self._simple_tokenize(code)

    def _simple_tokenize(self, code: str) -> List[str]:
        """Simple lexical tokenization"""
        # Remove comments
        code = self._remove_comments(code)

        # Split into tokens
        # Match: identifiers, numbers, strings, operators
        pattern = r'[a-zA-Z_][a-zA-Z0-9_]*|[0-9]+(?:\.[0-9]+)?|"[^"]*"|\'[^\']*\'|[^\s\w]'
        tokens = re.findall(pattern, code)

        return tokens

    def _remove_comments(self, code: str) -> str:
        """Remove Java comments"""
        # Remove single-line comments
        code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
        # Remove multi-line comments
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        return code

    def _jaccard_similarity(self, tokens1: List[str], tokens2: List[str]) -> float:
        """
        Compute Jaccard similarity

        Uses multiset Jaccard (takes token frequency into account)

        Args:
            tokens1: first token list
            tokens2: second token list

        Returns:
            float: Jaccard similarity [0, 1]
        """
        if not tokens1 and not tokens2:
            return 1.0

        if not tokens1 or not tokens2:
            return 0.0

        # Use Counter to compute multisets
        counter1 = Counter(tokens1)
        counter2 = Counter(tokens2)

        # Intersection (take minimum)
        intersection = sum((counter1 & counter2).values())

        # Union (take maximum)
        union = sum((counter1 | counter2).values())

        if union == 0:
            return 1.0

        return intersection / union

    def calculate_set_jaccard(self, tokens1: List[str], tokens2: List[str]) -> float:
        """
        Compute set Jaccard similarity (without considering duplicates)

        Args:
            tokens1: first token list
            tokens2: second token list

        Returns:
            float: Jaccard similarity [0, 1]
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
        Get token-level differences

        Args:
            user_code: user code
            gt_code: GT code

        Returns:
            dict: token difference information
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
