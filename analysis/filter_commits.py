#!/usr/bin/env python3
"""
Commit further filtering script -- Step 1

Executes the following three filtering steps in sequence:
  1. Filter Type3 (no objective evaluation metric)
  2. Tighten cutoff date (default 2019-01-01; can be relaxed individually for projects
     that rely entirely on early commits)
     - commons-math / gson: 2017-01-01 (all non-Type3 commits in these two projects
       predate 2019)
  3. Filter merge commits and oversized changes (changed files > MAX_FILES)

Usage:
  python analysis/filter_commits.py [--csv PATH] [--projects-root PATH]
                                    [--since YYYY-MM-DD] [--max-files N]
                                    [--out PATH]
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

# Ensure project root modules can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from git import Repo, GitCommandError, InvalidGitRepositoryError
except ImportError:
    print("[ERROR] Please install gitpython first: pip install gitpython")
    sys.exit(1)

# ── Default paths ──────────────────────────────────────────────────────────────
DEFAULT_CSV = "/Users/mac/Desktop/TestUpdate/qualified_commits_new.csv"
DEFAULT_PROJECTS_ROOT = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
DEFAULT_OUT = "/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv"
DEFAULT_SINCE = "2019-01-01"
DEFAULT_MAX_FILES = 20

# Per-project date relaxation overrides (all non-Type3 commits in these projects
# predate 2019, so they need to be relaxed individually)
PROJECT_DATE_OVERRIDES = {
    "commons-math": datetime(2016, 1, 1),
    "gson":         datetime(2016, 1, 1),
}
# ─────────────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="TUBench commit first-round precise filtering")
    p.add_argument("--csv", default=DEFAULT_CSV, help="Input CSV path")
    p.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT, help="Project root directory")
    p.add_argument("--since", default=DEFAULT_SINCE, help="Cutoff date (keep only commits after this date)")
    p.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                   help="Maximum changed files per commit (including test + source + other)")
    p.add_argument("--out", default=DEFAULT_OUT, help="Output CSV path")
    return p.parse_args()


def load_repos(projects_root: str, projects) -> dict:
    """Load all required git Repo objects"""
    repos = {}
    for proj in sorted(projects):
        path = os.path.join(projects_root, proj)
        if not os.path.isdir(path):
            print(f"  [WARN] Project directory not found: {path}")
            continue
        try:
            repos[proj] = Repo(path)
        except (InvalidGitRepositoryError, Exception) as e:
            print(f"  [WARN] Unable to load git repository {proj}: {e}")
    return repos


def resolve_commit(repo: Repo, short_hash: str):
    """Resolve a short hash to a full commit object; returns None on failure"""
    try:
        full = repo.git.rev_parse(short_hash)
        return repo.commit(full)
    except Exception:
        return None


def count_all_changed_files(commit) -> int:
    """Count total changed files compared to parent commit (all file types)"""
    if not commit.parents:
        return 0
    try:
        diffs = commit.parents[0].diff(commit)
        return len(list(diffs))
    except Exception:
        return 0


def main():
    args = parse_args()
    date_cutoff = datetime.strptime(args.since, "%Y-%m-%d")

    # ── Read CSV ──────────────────────────────────────────────────────────────
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    print(f"\n{'='*55}")
    print(f"  TUBench Commit Precise Filtering Step-1")
    print(f"{'='*55}")
    print(f"  Original commit count       : {total}")

    # ── Step 1: Filter Type3 ────────────────────────────────────────────────
    after_type3 = [r for r in rows if r["Type"].strip().lower() != "type 3"]
    n_type3 = total - len(after_type3)
    print(f"\n[Step 1] Filter Type3")
    print(f"  Eliminated Type3            : {n_type3}")
    print(f"  Remaining                   : {len(after_type3)}")

    # ── Load repos ───────────────────────────────────────────────────────────
    all_projects = {r["Project"].strip() for r in after_type3}
    print(f"\n  Loading {len(all_projects)} git repositories...")
    repos = load_repos(args.projects_root, all_projects)

    # ── Step 2 & 3: Date / merge / file count ────────────────────────────────
    passed = []
    stats = defaultdict(int)

    for r in after_type3:
        proj = r["Project"].strip()
        short_hash = r["CommitID"].strip()

        repo = repos.get(proj)
        if not repo:
            stats["no_repo"] += 1
            continue

        commit = resolve_commit(repo, short_hash)
        if commit is None:
            stats["resolve_fail"] += 1
            continue

        commit_date = datetime.fromtimestamp(commit.committed_date)

        # Step 2: Date filter (supports per-project relaxation overrides)
        effective_cutoff = PROJECT_DATE_OVERRIDES.get(proj, date_cutoff)
        if commit_date < effective_cutoff:
            stats["old_date"] += 1
            continue

        # Step 3a: merge commit
        if len(commit.parents) > 1:
            stats["merge"] += 1
            continue

        # Step 3b: oversized change
        n_files = count_all_changed_files(commit)
        if n_files > args.max_files:
            stats["large_change"] += 1
            continue

        passed.append({
            "Project": proj,
            "Type": r["Type"].strip(),
            "CommitID": short_hash,
            "FullHash": commit.hexsha,
            "Date": commit_date.strftime("%Y-%m-%d"),
            "ChangedFiles": n_files,
        })

    # ── Output statistics ─────────────────────────────────────────────────────
    print(f"\n[Step 2] Filter cutoff date < {args.since}")
    print(f"  Eliminated (date too old)   : {stats['old_date']}")
    print(f"\n[Step 3] Filter merge commits and oversized changes (>{args.max_files} files)")
    print(f"  Eliminated (merge commit)   : {stats['merge']}")
    print(f"  Eliminated (> {args.max_files} files)  : {stats['large_change']}")
    print(f"  Eliminated (hash resolve fail): {stats['resolve_fail'] + stats['no_repo']}")

    print(f"\n{'='*55}")
    print(f"  Final remaining commit count : {len(passed)}")
    print(f"{'='*55}")

    # Per-project statistics
    by_proj = defaultdict(int)
    by_type = defaultdict(int)
    for r in passed:
        by_proj[r["Project"]] += 1
        by_type[r["Type"]] += 1

    print("\n  Distribution by project:")
    for proj, cnt in sorted(by_proj.items()):
        print(f"    {proj:<30} {cnt}")

    print("\n  Distribution by Type:")
    for t, cnt in sorted(by_type.items()):
        print(f"    {t:<20} {cnt}")

    # ── Save results ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(args.out), exist_ok=True) if os.path.dirname(args.out) else None
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Project", "Type", "CommitID", "FullHash", "Date", "ChangedFiles"])
        writer.writeheader()
        writer.writerows(passed)

    print(f"\n  Results saved to: {args.out}\n")


if __name__ == "__main__":
    main()
