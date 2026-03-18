#!/usr/bin/env python3
"""
Commit 精筛脚本 —— Step 2 (重构版)

在 Step 1 结果基础上执行四步精筛:
  1. 质量过滤: MIN_TEST_LINES ≤ test_changed_lines ≤ MAX_TEST_LINES
  2. @Test 方法验证: 至少有一个 JUnit 4/5 测试方法被修改
  3. 语义分类: 按测试-代码关系分为三类
       test_breaking  —— 源码 API 变更导致旧测试失效（签名/异常声明改变）
       test_stale     —— 内部实现演化导致测试断言过时（但 API 未破坏）
       test_missing   —— 新增功能缺乏测试（新源码方法 + 新测试同步出现）
  4. 均衡采样: 项目多样性（≥8 项目, ≥3 commit/项目）+ 类别比例 3:4:3
              + 难易梯度标注（easy / medium / hard）

用法:
  python analysis/filter_commits_step2.py [--csv PATH] [--projects-root PATH]
                                           [--out PATH] [options]
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from git import Repo
except ImportError:
    print("[ERROR] 请先安装 gitpython: pip install gitpython")
    sys.exit(1)

# ── 默认参数 ──────────────────────────────────────────────────────────────────
DEFAULT_CSV            = "/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv"
DEFAULT_PROJECTS_ROOT  = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
DEFAULT_OUT            = "/Users/mac/Desktop/TestUpdate/filtered_commits_step2.csv"
DEFAULT_OUT_FULL       = "/Users/mac/Desktop/TestUpdate/filtered_commits_step2_full.csv"
DEFAULT_MIN_TEST_LINES = 5
DEFAULT_MAX_TEST_LINES = 200
DEFAULT_MIN_PER_PROJECT = 3
DEFAULT_TARGET_TOTAL    = 200

# Target category ratios:  Breaking 30% | Stale 40% | Missing 30%
CATEGORY_RATIOS = {'test_breaking': 0.30, 'test_stale': 0.40, 'test_missing': 0.30}

# Difficulty thresholds (total changed files, total diff lines across all files)
DIFF_EASY_FILES   = 2;  DIFF_EASY_LINES   = 30
DIFF_MEDIUM_FILES = 5;  DIFF_MEDIUM_LINES  = 100
# ──────────────────────────────────────────────────────────────────────────────

TEST_PATH_PATTERNS   = ['src/test/java', 'test/java', 'src/test']
SOURCE_PATH_PATTERNS = ['src/main/java', 'main/java', 'src/main']

# Java method-signature regex applied to diff lines
_SKIP_KEYWORDS = {'if', 'while', 'for', 'switch', 'catch', 'return', 'else',
                  'try', 'new', 'class', 'interface', 'enum', 'assert', 'throw'}
_MOD   = r'(?:(?:public|protected|private|static|final|abstract|synchronized|default|native)\s+)*'
_GTYPE = r'(?:<[^>]+>\s+)?'
_TYPE  = r'[\w$][\w$.<>, \[\]]+'
_NAME  = r'([\w$]+)'
_PAR   = r'\s*\('
SIG_RE = re.compile(rf'^\s*{_MOD}{_GTYPE}{_TYPE}\s+{_NAME}{_PAR}')

TEST_ANNOT_RE = re.compile(r'@(Test|ParameterizedTest|RepeatedTest|TestFactory)\b')


def parse_args():
    p = argparse.ArgumentParser(description="TUBench commit 精筛 Step-2（语义分类版）")
    p.add_argument("--csv",                   default=DEFAULT_CSV)
    p.add_argument("--projects-root",         default=DEFAULT_PROJECTS_ROOT)
    p.add_argument("--out",                   default=DEFAULT_OUT)
    p.add_argument("--out-full",              default=DEFAULT_OUT_FULL,
                   help="保存质量过滤+去重后、均衡采样前的完整集合")
    p.add_argument("--min-test-lines", type=int, default=DEFAULT_MIN_TEST_LINES)
    p.add_argument("--max-test-lines", type=int, default=DEFAULT_MAX_TEST_LINES)
    p.add_argument("--min-per-project",type=int, default=DEFAULT_MIN_PER_PROJECT)
    p.add_argument("--target-total",   type=int, default=DEFAULT_TARGET_TOTAL)
    return p.parse_args()


# ── Low-level diff helpers ─────────────────────────────────────────────────────

def is_test_file(path: str) -> bool:
    return path.endswith('.java') and any(p in path for p in TEST_PATH_PATTERNS)


def is_source_file(path: str) -> bool:
    return path.endswith('.java') and any(p in path for p in SOURCE_PATH_PATTERNS)


def count_diff_changed_lines(diff_text: str) -> int:
    """Count non-blank added+removed lines in a unified diff."""
    count = 0
    for line in diff_text.split('\n'):
        if (line.startswith('+') and not line.startswith('+++')) or \
           (line.startswith('-') and not line.startswith('---')):
            if line[1:].strip():
                count += 1
    return count


def _diff_method_names(diff_text: str):
    """Return (added_method_names, removed_method_names) sets from a diff."""
    added, removed = set(), set()
    for line in diff_text.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            m = SIG_RE.match(line[1:])
            if m and m.group(1) not in _SKIP_KEYWORDS:
                added.add(m.group(1))
        elif line.startswith('-') and not line.startswith('---'):
            m = SIG_RE.match(line[1:])
            if m and m.group(1) not in _SKIP_KEYWORDS:
                removed.add(m.group(1))
    return added, removed


def _diff_test_annotations(diff_text: str):
    """Return (new_annots, removed_annots) counts of @Test-family annotations."""
    new_cnt, rem_cnt = 0, 0
    for line in diff_text.split('\n'):
        if line.startswith('+') and not line.startswith('+++'):
            if TEST_ANNOT_RE.search(line[1:]):
                new_cnt += 1
        elif line.startswith('-') and not line.startswith('---'):
            if TEST_ANNOT_RE.search(line[1:]):
                rem_cnt += 1
    return new_cnt, rem_cnt


def get_test_method_ranges(content: str) -> list:
    """
    Extract @Test method info from Java source using brace-counting.
    Returns list of {'class': str, 'method': str, 'start_line': int, 'end_line': int}.
    """
    lines = content.split('\n')
    results = []
    current_class = 'Unknown'
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        cls_m = re.match(
            r'(?:(?:public|protected|private|abstract|final|static)\s+)*class\s+(\w+)', stripped)
        if cls_m:
            current_class = cls_m.group(1)
        if re.match(r'@(Test|ParameterizedTest|RepeatedTest|TestFactory)\b', stripped):
            method_name = None
            for j in range(i + 1, min(i + 6, len(lines))):
                mm = re.search(r'(?:public|protected|private|void|\w+)\s+(\w+)\s*\(', lines[j])
                if mm:
                    method_name = mm.group(1)
                    break
            if method_name:
                brace_count, found_open, start_line, end_line = 0, False, i + 1, None
                k = i
                while k < len(lines):
                    for ch in lines[k]:
                        if ch == '{':
                            brace_count += 1; found_open = True
                        elif ch == '}':
                            brace_count -= 1
                    if found_open and brace_count == 0:
                        end_line = k + 1; break
                    k += 1
                if end_line:
                    results.append({'class': current_class, 'method': method_name,
                                    'start_line': start_line, 'end_line': end_line})
                i = k + 1
                continue
        i += 1
    return results


def get_added_line_numbers(diff_text: str) -> list:
    """Return 1-indexed line numbers of added lines (new-file side) from a unified diff."""
    nums, new_line = [], 0
    hunk_re = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')
    for line in diff_text.split('\n'):
        m = hunk_re.match(line)
        if m:
            new_line = int(m.group(1)); continue
        if line.startswith(('+++', '---', 'diff', 'index', 'Binary')):
            continue
        if line.startswith('+'):
            nums.append(new_line); new_line += 1
        elif not line.startswith('-'):
            new_line += 1
    return nums


# ── Semantic classification ────────────────────────────────────────────────────

def classify_test_change_type(repo: Repo, full_hash: str,
                               test_files: list, source_files: list) -> str:
    """
    Classify the commit into one of three semantic categories:

      test_breaking  – Source API changed (method renamed / signature altered /
                       throws-clause modified) AND existing tests were modified.
                       → Tests fail to compile or assert against the new API.

      test_missing   – New source methods appeared AND net-new @Test methods
                       were added (new functionality with its own new tests).
                       → The test update task is: add coverage for the new code.

      test_stale     – Everything else: internal implementation evolved, tests
                       had to update expected values / mocks / structure, but
                       the public API surface was not broken outright.

    Decision priority:  test_breaking > test_missing > test_stale
    """
    try:
        parent_hash = repo.commit(full_hash).parents[0].hexsha
    except Exception:
        return 'test_stale'

    # ── Analyse test files ───────────────────────────────────────────────────
    total_new_annots = 0
    total_rem_annots = 0
    for tf in test_files:
        try:
            diff = repo.git.diff('-U3', parent_hash, full_hash, '--', tf)
            n, r = _diff_test_annotations(diff)
            total_new_annots += n
            total_rem_annots += r
        except Exception:
            pass

    # ── Analyse source files ─────────────────────────────────────────────────
    sig_changes    = 0   # methods whose name appears in BOTH added and removed lines
    new_src_methods = 0  # method names that only appear in added lines
    for sf in source_files:
        try:
            diff = repo.git.diff('-U3', parent_hash, full_hash, '--', sf)
            added_names, removed_names = _diff_method_names(diff)
            sig_changes    += len(added_names & removed_names)
            new_src_methods += len(added_names - removed_names)
        except Exception:
            pass

    # ── Decision tree ────────────────────────────────────────────────────────
    net_new_tests = total_new_annots - total_rem_annots

    # Priority 1 – API break: renamed/re-signatured methods + tests touched
    if sig_changes > 0 and (total_rem_annots > 0 or total_new_annots > 0):
        return 'test_breaking'

    # Priority 2 – New feature: new source methods + net new test methods
    if net_new_tests > 0 and new_src_methods > 0:
        return 'test_missing'

    # Default – internal evolution / assertion update / mocking change
    return 'test_stale'


def compute_difficulty(changed_files_total: int, total_diff_lines: int) -> str:
    """
    Classify commit difficulty based on breadth (files) and depth (lines):
      easy   – ≤ 2 changed files  AND ≤ 30 total diff lines
      medium – ≤ 5 changed files  AND ≤ 100 total diff lines
      hard   – > 5 changed files  OR  > 100 total diff lines
    """
    if changed_files_total <= DIFF_EASY_FILES and total_diff_lines <= DIFF_EASY_LINES:
        return 'easy'
    if changed_files_total <= DIFF_MEDIUM_FILES and total_diff_lines <= DIFF_MEDIUM_LINES:
        return 'medium'
    return 'hard'


def analyze_commit(repo: Repo, full_hash: str, changed_files_total: int) -> dict | None:
    """
    Extended commit analysis: quality check + semantic classification + difficulty.

    Returns dict with keys:
      test_changed_lines, has_test_method, changed_test_methods,
      test_change_type, difficulty, src_changed_lines
    or None on failure.
    """
    try:
        commit = repo.commit(full_hash)
        if not commit.parents:
            return None
        parent_hash = commit.parents[0].hexsha

        # 1. Enumerate changed files (cheap)
        try:
            all_changed = repo.git.diff('--name-only', parent_hash, full_hash).splitlines()
        except Exception:
            return None

        test_files = [f for f in all_changed if is_test_file(f)]
        src_files  = [f for f in all_changed if is_source_file(f)]

        if not test_files:
            return {'test_changed_lines': 0, 'has_test_method': False,
                    'changed_test_methods': [], 'test_change_type': 'test_stale',
                    'difficulty': 'easy', 'src_changed_lines': 0}

        # 2. Quality metrics (test files only)
        total_test_lines     = 0
        has_test_method      = False
        changed_test_methods = []

        for path in test_files:
            try:
                diff_text = repo.git.diff('-U3', parent_hash, full_hash, '--', path)
            except Exception:
                continue
            total_test_lines += count_diff_changed_lines(diff_text)
            try:
                new_content = repo.git.show(f'{full_hash}:{path}')
            except Exception:
                continue
            test_ranges = get_test_method_ranges(new_content)
            if not test_ranges:
                continue
            for line_no in get_added_line_numbers(diff_text):
                for tm in test_ranges:
                    if tm['start_line'] <= line_no <= tm['end_line']:
                        has_test_method = True
                        key = (tm['class'], tm['method'])
                        if key not in changed_test_methods:
                            changed_test_methods.append(key)

        # 3. Source line count (for difficulty)
        src_changed_lines = 0
        for sf in src_files:
            try:
                src_changed_lines += count_diff_changed_lines(
                    repo.git.diff('-U0', parent_hash, full_hash, '--', sf))
            except Exception:
                pass

        # 4. Semantic classification
        test_change_type = classify_test_change_type(
            repo, full_hash, test_files, src_files)

        # 5. Difficulty
        total_diff_lines = total_test_lines + src_changed_lines
        difficulty = compute_difficulty(changed_files_total, total_diff_lines)

        return {
            'test_changed_lines':   total_test_lines,
            'has_test_method':      has_test_method,
            'changed_test_methods': changed_test_methods,
            'test_change_type':     test_change_type,
            'difficulty':           difficulty,
            'src_changed_lines':    src_changed_lines,
        }
    except Exception:
        return None


# ── Balanced sampling ─────────────────────────────────────────────────────────

def balance_with_categories(rows: list, min_per_project: int,
                             target_total: int,
                             cat_ratios: dict = CATEGORY_RATIOS) -> list:
    """
    Two-phase balanced sampling:

    Phase 1 – Project diversity
        • Drop projects with < min_per_project commits.
        • Apply proportional per-project cap so no single project dominates,
          while honouring category diversity within each project's allocation.

    Phase 2 – Category balancing
        • From the project-diverse pool, sample by category to approach
          the target ratios (test_breaking 30%, test_stale 40%, test_missing 30%).
        • Within each category, take proportionally from each project.
        • If a category is short of its target, the remaining budget is
          redistributed to whichever category has surplus.
    """
    by_project = defaultdict(list)
    for r in rows:
        by_project[r['Project']].append(r)

    # ── Phase 1: project diversity filter + per-project cap ──────────────────
    qualified = {p: c for p, c in by_project.items() if len(c) >= min_per_project}
    removed = set(by_project) - set(qualified)
    if removed:
        print(f"  [均衡] 移除项目 (< {min_per_project} commits): {sorted(removed)}")
    print(f"  [均衡] 有效项目数: {len(qualified)}, "
          f"可用 commit: {sum(len(c) for c in qualified.values())}")

    sorted_proj = sorted(qualified.items(), key=lambda x: len(x[1]), reverse=True)
    n_proj = len(sorted_proj)
    project_pools: dict[str, list] = {}     # project → capped commits
    remaining_budget = target_total
    for i, (proj, commits) in enumerate(sorted_proj):
        fair_share = max(remaining_budget // max(n_proj - i, 1), min_per_project)
        cap        = max(min(len(commits), fair_share), min_per_project)
        # Within cap, preserve category distribution proportionally
        by_cat = defaultdict(list)
        for c in commits:
            by_cat[c['TestChangeType']].append(c)
        selected = []
        for cat, cat_ratio in cat_ratios.items():
            want = max(1, round(cap * cat_ratio)) if by_cat[cat] else 0
            selected.extend(by_cat[cat][:want])
        # Fill remaining slots with any leftover
        taken_ids = {id(r) for r in selected}
        for c in commits:
            if len(selected) >= cap:
                break
            if id(c) not in taken_ids:
                selected.append(c); taken_ids.add(id(c))
        project_pools[proj] = selected
        remaining_budget = max(0, remaining_budget - cap)

    diverse_pool = [r for commits in project_pools.values() for r in commits]
    print(f"  [均衡] 项目多样性过滤后: {len(diverse_pool)} commits")

    # ── Phase 2: category balancing ──────────────────────────────────────────
    by_category: dict[str, list] = defaultdict(list)
    for r in diverse_pool:
        by_category[r['TestChangeType']].append(r)

    final: list = []
    unmet_budget = 0
    order = sorted(cat_ratios, key=lambda c: len(by_category[c]))  # scarce first

    for cat in order:
        target_cat = round(target_total * cat_ratios[cat]) + unmet_budget
        pool = by_category[cat]
        if len(pool) >= target_cat:
            # Proportional across projects within this category
            by_proj_cat = defaultdict(list)
            for r in pool:
                by_proj_cat[r['Project']].append(r)
            taken = []
            for proj_c in sorted(by_proj_cat.values(), key=len, reverse=True):
                share = max(1, round(target_cat * len(proj_c) / len(pool)))
                taken.extend(proj_c[:share])
                if len(taken) >= target_cat:
                    break
            final.extend(taken[:target_cat])
            unmet_budget = 0
        else:
            # Take everything available, carry deficit forward
            final.extend(pool)
            unmet_budget = target_cat - len(pool)

    return final


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    with open(args.csv, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    print(f"\n{'='*60}")
    print(f"  TUBench Commit 精筛 Step-2（语义分类 + 均衡采样版）")
    print(f"{'='*60}")
    print(f"  输入 commit 数: {total}")

    # Load repos
    all_projects = {r['Project'].strip() for r in rows}
    repos: dict[str, Repo] = {}
    print(f"\n  加载 {len(all_projects)} 个 git 仓库...")
    for proj in sorted(all_projects):
        path = os.path.join(args.projects_root, proj)
        try:
            repos[proj] = Repo(path)
        except Exception:
            print(f"  [WARN] 无法加载仓库: {proj}")

    # ── Step 1: Quality + classification ────────────────────────────────────
    print(f"\n  分析 {total} 个 commits …")
    passed_quality: list[dict] = []
    stats: dict[str, int] = defaultdict(int)

    for idx, r in enumerate(rows, 1):
        proj      = r['Project'].strip()
        full_hash = r.get('FullHash', '').strip() or r.get('CommitID', '').strip()
        changed_files_total = int(r.get('ChangedFiles', '0') or '0')

        repo = repos.get(proj)
        if not repo:
            stats['no_repo'] += 1; continue

        result = analyze_commit(repo, full_hash, changed_files_total)
        if result is None:
            stats['analysis_fail'] += 1; continue

        tl = result['test_changed_lines']
        if tl < args.min_test_lines:
            stats['too_few_lines'] += 1; continue
        if tl > args.max_test_lines:
            stats['too_many_lines'] += 1; continue
        if not result['has_test_method']:
            stats['no_test_method'] += 1; continue

        passed_quality.append({
            'Project':          proj,
            'Type':             r['Type'].strip(),
            'CommitID':         r.get('CommitID', '').strip(),
            'FullHash':         full_hash,
            'Date':             r.get('Date', '').strip(),
            'ChangedFiles':     changed_files_total,
            'TestChangedLines': tl,
            'SrcChangedLines':  result['src_changed_lines'],
            'TestChangeType':   result['test_change_type'],
            'Difficulty':       result['difficulty'],
            'ChangedTestMethods': '|'.join(
                f"{c}.{m}" for c, m in result['changed_test_methods']),
        })

        if idx % 50 == 0:
            print(f"    进度: {idx}/{total}  (通过质量过滤: {len(passed_quality)})")

    print(f"\n  [质量过滤]")
    print(f"    测试行数过少 (< {args.min_test_lines})    : {stats['too_few_lines']}")
    print(f"    测试行数过多 (> {args.max_test_lines})   : {stats['too_many_lines']}")
    print(f"    无 @Test 方法变更         : {stats['no_test_method']}")
    print(f"    分析失败 / 无仓库         : {stats['analysis_fail'] + stats['no_repo']}")
    print(f"    质量过滤后剩余            : {len(passed_quality)}")

    # Natural category distribution
    nat = defaultdict(int)
    for r in passed_quality:
        nat[r['TestChangeType']] += 1
    pq = len(passed_quality) or 1
    print(f"\n  [质量过滤后语义分布]")
    for cat in ('test_breaking', 'test_stale', 'test_missing'):
        bar = '█' * nat[cat]
        print(f"    {cat:<16}: {nat[cat]:>3}  ({nat[cat]/pq*100:.1f}%)  {bar}")

    # ── Step 2: Deduplication ────────────────────────────────────────────────
    seen_keys: set[tuple] = set()
    after_dedup: list[dict] = []
    dedup_count = 0
    for r in passed_quality:
        methods = [m for m in r['ChangedTestMethods'].split('|') if m]
        new_keys = [(r['Project'], m) for m in methods
                    if (r['Project'], m) not in seen_keys]
        if not methods or new_keys:
            for k in new_keys:
                seen_keys.add(k)
            after_dedup.append(r)
        else:
            dedup_count += 1
    print(f"\n  [去重] 淘汰: {dedup_count}  剩余: {len(after_dedup)}")

    # ── Step 3: Balanced sampling ────────────────────────────────────────────
    print(f"\n  [均衡采样] 目标: {args.target_total} commits, "
          f"项目 ≥ {args.min_per_project}, "
          f"类别比例 Breaking:Stale:Missing = 3:4:3")
    final = balance_with_categories(
        after_dedup, args.min_per_project, args.target_total, CATEGORY_RATIOS)

    # ── Summary ──────────────────────────────────────────────────────────────
    by_proj   = defaultdict(int)
    by_type   = defaultdict(int)
    by_cat    = defaultdict(int)
    by_diff   = defaultdict(int)
    for r in final:
        by_proj[r['Project']]      += 1
        by_type[r['Type']]         += 1
        by_cat[r['TestChangeType']] += 1
        by_diff[r['Difficulty']]    += 1

    n = len(final) or 1
    print(f"\n{'='*60}")
    print(f"  最终 commit 数  : {len(final)}")
    print(f"  保留项目数      : {len(by_proj)}")
    print(f"{'='*60}")

    print("\n  各项目分布:")
    for proj, cnt in sorted(by_proj.items()):
        print(f"    {proj:<32} {cnt}")

    print("\n  语义类别分布 (目标 3:4:3):")
    for cat in ('test_breaking', 'test_stale', 'test_missing'):
        cnt = by_cat[cat]
        bar = '█' * cnt
        print(f"    {cat:<16}: {cnt:>3}  ({cnt/n*100:.1f}%)  {bar}")

    print("\n  难易梯度分布:")
    for d in ('easy', 'medium', 'hard'):
        cnt = by_diff[d]
        print(f"    {d:<8}: {cnt:>3}  ({cnt/n*100:.1f}%)")

    print("\n  Type 1 / Type 2 分布:")
    for t, cnt in sorted(by_type.items()):
        print(f"    {t:<12}: {cnt:>3}  ({cnt/n*100:.1f}%)")

    # ── Save ─────────────────────────────────────────────────────────────────
    fieldnames = ['Project', 'Type', 'CommitID', 'FullHash', 'Date',
                  'ChangedFiles', 'TestChangedLines', 'SrcChangedLines',
                  'TestChangeType', 'Difficulty', 'ChangedTestMethods']

    # Full set (quality-filtered + deduped, pre-balancing, 314 commits)
    with open(args.out_full, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(after_dedup)
    print(f"\n  完整集合（{len(after_dedup)} commits）已保存至: {args.out_full}")

    # Balanced set (161 commits)
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final)
    print(f"  均衡采样集合（{len(final)} commits）已保存至: {args.out}\n")


if __name__ == '__main__':
    main()

