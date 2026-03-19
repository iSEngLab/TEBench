"""
Shared prompt templates for outdated test identification and update tasks.

This module is used by all baseline agents to keep prompt policy consistent.
"""

UNIFIED_PROMPT = """You are working on a test evolution task for a Java Maven project.

## Context

The source code has already been updated in the current HEAD, while test code may now be outdated.
Your task is to identify outdated tests and update them so they reflect current source behavior.

## Allowed and Forbidden Changes

- Allowed:
  - Test files (for example `src/test/**`)
  - Test resources/config files (for example `src/test/resources/**`)
  - Maven/build configuration needed to execute or align tests (for example `pom.xml`, module poms, surefire/failsafe config)
- Forbidden:
  - Any production source changes under `src/main/**`
  - Any "fix" that makes tests pass by changing production logic instead of updating tests/build setup

## Workflow

1. Inspect source changes with `git diff HEAD~1 -- src/main/`.
2. Inspect relevant tests and test configs.
3. Run a baseline verification to reproduce current behavior (prefer targeted tests first, then full test run if needed).
4. Suggestion: use JaCoCo (for example `target/site/jacoco/jacoco.xml`) to check coverage of changed production code.
5. Apply minimal, test-side/build-side changes.
6. Re-run verification and coverage checks; iterate only when there is a concrete next fix.

## Termination Conditions

Stop when any of these holds:
- Relevant tests now pass AND coverage requirements below are satisfied, OR
- Remaining failures are clearly unrelated/pre-existing and cannot be resolved without editing `src/main/**`, OR
- A new verification run shows no actionable new signal compared with the previous run.

Coverage requirements (pass-only is NOT enough):
- Passing tests alone is insufficient if changed production behavior is still weakly tested.
- Suggest using JaCoCo coverage results to confirm changed production code is adequately covered.

## Output Requirements

- Do not commit changes.
- Keep modifications minimal and explainable.
- Before finishing, provide a concise summary:
  - files changed
  - why they changed
  - final verification command(s) and outcomes
  - coverage evidence (JaCoCo)
  - unresolved blockers (if any)
"""


def get_prompt_for_type(commit_type: str) -> str:
    """
    Keep API compatibility with existing callers.
    We intentionally do not vary prompt by commit type.
    """
    _ = commit_type
    return UNIFIED_PROMPT


def format_task_prompt(commit_type: str,
                       project_name: str,
                       additional_context: str = "") -> str:
    """
    Format prompt with lightweight task metadata.
    Commit type is accepted for compatibility, but not used for template branching.
    """
    _ = commit_type
    base_prompt = get_prompt_for_type(commit_type)

    context_lines = [f"Project: {project_name}"]
    if additional_context and additional_context.strip():
        context_lines.extend(["", additional_context.strip()])

    context_header = "\n".join(context_lines) + "\n\n---\n\n"
    return context_header + base_prompt
