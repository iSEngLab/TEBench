"""
Backward-compatible prompt exports for Codex runner.
Shared prompt logic lives in baseline/shared_test_update_prompt.py
"""

from baseline.shared_test_update_prompt import (  # noqa: F401
    UNIFIED_PROMPT,
    format_task_prompt,
    get_prompt_for_type,
)
