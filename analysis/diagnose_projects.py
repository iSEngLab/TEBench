#!/usr/bin/env python3
"""
Diagnostic: per-project breakdown of WHY commits are eliminated in Step 1 & Step 2.
Prints two tables:
  Table 1 -- Step 1 elimination reasons (type3 / pre-2019 / merge / >20 files)
  Table 2 -- Step 2 quality reasons for commits that survived Step 1
             (too few test lines / too many test lines / no @Test method)
"""

import csv
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from git import Repo

PROJECTS_ROOT  = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
CSV_ORIGINAL   = "/Users/mac/Desktop/TestUpdate/qualified_commits_new.csv"
CSV_STEP1      = "/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv"
SINCE          = datetime(2019, 1, 1)
MAX_FILES      = 20
MIN_TEST_LINES = 5
MAX_TEST_LINES = 80   # current threshold; change to 120 to see impact

ALL_14 = [
    "commons-cli", "commons-codec", "commons-collections", "commons-compress",
    "commons-csv", "commons-jxpath", "commons-lang", "commons-math",
    "gson", "jackson-core", "jackson-databind", "jackson-dataformat-xml",
    "jfreechart", "jsoup",
]

TEST_PATTERNS = ["src/test/java", "test/java", "src/test"]


def is_test_file(path):
    return path.endswith(".java") and any(p in path for p in TEST_PATTERNS)


def count_diff_changed_lines(diff_text):
    count = 0
    for line in diff_text.split("\n"):
        if (line.startswith("+") and not line.startswith("+++")) or \
           (line.startswith("-") and not line.startswith("---")):
            if line[1:].strip():
                count += 1
    return count


def get_test_method_ranges(content):
    lines = content.split("\n")
    results = []
    current_class = "Unknown"
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        cls_m = re.match(
            r"(?:(?:public|protected|private|abstract|final|static)\s+)*class\s+(\w+)",
            stripped)
        if cls_m:
            current_class = cls_m.group(1)
        if re.match(r"@Test\b", stripped):
            method_name = None
            for j in range(i + 1, min(i + 6, len(lines))):
                mm = re.search(r"(?:public|protected|private|void|\w+)\s+(\w+)\s*\(", lines[j])
                if mm:
                    method_name = mm.group(1)
                    break
            if method_name:
                brace_count = 0
                found_open = False
                start_line = i + 1
                end_line = None
                k = i
                while k < len(lines):
                    for ch in lines[k]:
                        if ch == "{":
                            brace_count += 1
                            found_open = True
                        elif ch == "}":
                            brace_count -= 1
                    if found_open and brace_count == 0:
                        end_line = k + 1
                        break
                    k += 1
                if end_line:
                    results.append({"class": current_class, "method": method_name,
                                    "start_line": start_line, "end_line": end_line})
                i = k + 1
                continue
        i += 1
    return results


def get_added_line_numbers(diff_text):
    nums = []
    new_line = 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in diff_text.split("\n"):
        m = hunk_re.match(line)
        if m:
            new_line = int(m.group(1))
            continue
        if line.startswith(("+++", "---", "diff", "index", "Binary")):
            continue
        if line.startswith("+"):
            nums.append(new_line)
            new_line += 1
        elif line.startswith("-"):
            pass
        else:
            new_line += 1
    return nums


def analyze_commit_quality(repo, full_hash, min_lines, max_lines):
    """Returns (test_lines, has_test_method) or None on error."""
    try:
        commit = repo.commit(full_hash)
        if not commit.parents:
            return None
        parent_hash = commit.parents[0].hexsha
        changed_files = repo.git.diff("--name-only", parent_hash, full_hash).splitlines()
        test_files = [f for f in changed_files if is_test_file(f)]
        if not test_files:
            return (0, False)
        total_lines = 0
        has_test_method = False
        for path in test_files:
            try:
                diff_text = repo.git.diff("-U3", parent_hash, full_hash, "--", path)
            except Exception:
                continue
            total_lines += count_diff_changed_lines(diff_text)
            try:
                new_content = repo.git.show(f"{full_hash}:{path}")
            except Exception:
                continue
            test_ranges = get_test_method_ranges(new_content)
            added_lines = get_added_line_numbers(diff_text)
            for ln in added_lines:
                for tm in test_ranges:
                    if tm["start_line"] <= ln <= tm["end_line"]:
                        has_test_method = True
        return (total_lines, has_test_method)
    except Exception:
        return None


def main():
    original = list(csv.DictReader(open(CSV_ORIGINAL)))
    step1    = list(csv.DictReader(open(CSV_STEP1)))

    # ── Load repos ────────────────────────────────────────────────────────────
    repos = {}
    for proj in ALL_14:
        path = os.path.join(PROJECTS_ROOT, proj)
        try:
            repos[proj] = Repo(path)
        except Exception:
            repos[proj] = None

    # ═══════════════════════════════════════════════════════════════════════════
    # TABLE 1 -- Step 1 elimination reasons
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 78)
    print("TABLE 1  --  Step-1 elimination reasons (each row=project, columns=elimination reason counts)")
    print("=" * 78)
    hdr = f"{'Project':<26} {'Total':>6} {'Type3':>6} {'Pre-2019':>9} {'Merge':>6} {'>20f':>5} {'Step1 OK':>9}"
    print(hdr)
    print("-" * 78)

    step1_ok_by_proj = defaultdict(int)
    for r in step1:
        step1_ok_by_proj[r["Project"].strip()] += 1

    for proj in ALL_14:
        proj_rows = [r for r in original if r["Project"].strip() == proj]
        repo = repos.get(proj)
        n_type3 = n_pre2019 = n_merge = n_large = n_ok = 0
        for r in proj_rows:
            t = r["Type"].strip().lower()
            if "type 3" in t or "type3" in t:
                n_type3 += 1
                continue
            if not repo:
                n_pre2019 += 1
                continue
            try:
                c = repo.commit(repo.git.rev_parse(r["CommitID"].strip()))
                cd = datetime.fromtimestamp(c.committed_date)
                if cd < SINCE:
                    n_pre2019 += 1
                    continue
                if len(c.parents) > 1:
                    n_merge += 1
                    continue
                if c.parents:
                    nf = len(list(c.parents[0].diff(c)))
                    if nf > MAX_FILES:
                        n_large += 1
                        continue
                n_ok += 1
            except Exception:
                n_pre2019 += 1
        total = len(proj_rows)
        mark = " <- ZERO" if n_ok == 0 else (" <- <5" if n_ok < 5 else "")
        print(f"{proj:<26} {total:>6} {n_type3:>6} {n_pre2019:>9} {n_merge:>6} {n_large:>5} {n_ok:>9}{mark}")

    # ═══════════════════════════════════════════════════════════════════════════
    # TABLE 2 -- Step 2 quality reasons (for step1 survivors)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 90)
    print(f"TABLE 2  --  Step-2 quality filter reasons (max_test_lines={MAX_TEST_LINES})")
    print("=" * 90)
    hdr2 = (f"{'Project':<26} {'In':>5} {'<5ln':>5} {'>'+str(MAX_TEST_LINES)+'ln':>7} "
            f"{'No@Test':>8} {'Fail':>5} {'Pass':>6}  avg_lines  p5  p25  p50  p75  p95")
    print(hdr2)
    print("-" * 90)

    by_proj = defaultdict(list)
    for r in step1:
        by_proj[r["Project"].strip()].append(r)

    for proj in ALL_14:
        proj_rows = by_proj.get(proj, [])
        if not proj_rows:
            print(f"{proj:<26} {'0':>5}  (no step1 survivors)")
            continue
        repo = repos.get(proj)
        n_few = n_many = n_no_test = n_fail = n_pass = 0
        line_counts = []
        for r in proj_rows:
            fh = r.get("FullHash", "").strip() or r.get("CommitID", "").strip()
            res = analyze_commit_quality(repo, fh, MIN_TEST_LINES, MAX_TEST_LINES) if repo else None
            if res is None:
                n_fail += 1
                continue
            tl, has_t = res
            line_counts.append(tl)
            if tl < MIN_TEST_LINES:
                n_few += 1
            elif tl > MAX_TEST_LINES:
                n_many += 1
            elif not has_t:
                n_no_test += 1
            else:
                n_pass += 1
        # percentiles
        lc_sorted = sorted(line_counts)
        def pct(lst, p):
            if not lst: return 0
            idx = int(len(lst) * p / 100)
            return lst[min(idx, len(lst)-1)]
        avg = round(sum(line_counts)/len(line_counts), 1) if line_counts else 0
        mark2 = " <- <5" if n_pass < 5 else ""
        print(f"{proj:<26} {len(proj_rows):>5} {n_few:>5} {n_many:>7} {n_no_test:>8} "
              f"{n_fail:>5} {n_pass:>6}  {avg:>8}  "
              f"{pct(lc_sorted,5):>3}  {pct(lc_sorted,25):>3}  "
              f"{pct(lc_sorted,50):>3}  {pct(lc_sorted,75):>3}  "
              f"{pct(lc_sorted,95):>3}{mark2}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
