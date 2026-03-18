"""
Prompt templates for outdated test identification and update tasks.
"""

SIMPLE_PROMPT = """You are working on a test evolution task for a Java Maven project.

## Context

The source code in `src/main/java/` has been modified, but the corresponding test code in `src/test/java/` has NOT been updated yet. Some tests may now be outdated — they may fail to compile, fail at runtime, or no longer adequately cover the changed code.

Your task is to analyze the source code changes, identify which tests are affected, and update them accordingly.

## Steps

1. Use `git diff HEAD~1 -- src/main/java/` to understand what source code changed.
2. Read the relevant test files in `src/test/java/` to understand the current test code.
3. Run `mvn clean test -Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true` to see if there are compilation errors or test failures.
4. Based on your analysis, determine which test methods need to be:
   - **Updated**: Existing test methods whose assertions, expected values, or API usage are now outdated.
   - **Added**: New test methods needed to cover new functionality.
   - **Deleted**: Test methods that test removed or obsolete functionality.
5. Apply the necessary changes to the test files.
6. Run `mvn clean test -Drat.skip=true -Denforcer.skip=true -Dcheckstyle.skip=true` again to verify your changes compile and pass.
7. If tests fail, iterate and fix until they pass.

## Important Constraints

- Do NOT modify any source code in `src/main/java/`. Only modify files in `src/test/java/`.
- You may use `git log`, `git show`, `git diff`, etc. to browse the current HEAD and any ancestor commits (HEAD~1, HEAD~2, ...) to understand the project's history and coding patterns. However, you MUST NOT check out, show, or diff any commits that come AFTER the current HEAD. The current HEAD is the latest state — there are no "future" commits to look at. Do NOT attempt to find or access any commit beyond HEAD.
- Do NOT commit your changes — leave all modifications in the working directory.
- Preserve the original test intent and structure when possible.
- Make minimal changes — only update what is necessary.

Start now by analyzing the source code changes with `git diff HEAD~1 -- src/main/java/`."""


def get_prompt_for_type(commit_type: str) -> str:
    """
    Get the appropriate prompt based on commit type.

    Args:
        commit_type: 'type1', 'type2', 'type3', or None

    Returns:
        str: The prompt text
    """
    return SIMPLE_PROMPT


def format_task_prompt(commit_type: str,
                       project_name: str,
                       additional_context: str = "") -> str:
    """
    Format a complete task prompt with context.

    Args:
        commit_type: Type of the commit
        project_name: Name of the project
        additional_context: Additional context information

    Returns:
        str: Formatted prompt
    """
    base_prompt = get_prompt_for_type(commit_type)

    context_header = f"""Project: {project_name}
Type: {commit_type}

{additional_context}

---

"""

    return context_header + base_prompt
