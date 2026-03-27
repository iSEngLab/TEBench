"""
TUBench Evaluation Module - for evaluating the effectiveness of outdated test case repair methods

Evaluation dimensions:
1. Executability - whether tests can compile and pass
2. Coverage Overlap - the overlap between coverage increment from user modifications and GT
3. Modification Effort - token-based Jaccard similarity
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
