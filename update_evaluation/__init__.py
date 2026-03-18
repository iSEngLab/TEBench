"""
TUBench 评估模块 - 用于评估过时测试用例修复方法的效果

评估维度：
1. 可执行性 (Executability) - 测试是否能编译通过、测试通过
2. 覆盖增量重合度 (Coverage Overlap) - 用户修改带来的覆盖增量与GT的重合程度
3. 改动量 (Modification Effort) - 基于token的Jaccard相似度
"""

from .worktree_manager import WorktreeManager
from .changed_method_extractor import ChangedMethodExtractor
from .executability_evaluator import ExecutabilityEvaluator
from .coverage_increment_analyzer import CoverageIncrementAnalyzer
from .modification_effort_calculator import ModificationEffortCalculator
from .evaluation_orchestrator import EvaluationOrchestrator

__all__ = [
    'WorktreeManager',
    'ChangedMethodExtractor',
    'ExecutabilityEvaluator',
    'CoverageIncrementAnalyzer',
    'ModificationEffortCalculator',
    'EvaluationOrchestrator'
]
