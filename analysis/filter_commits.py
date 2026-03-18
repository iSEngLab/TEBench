#!/usr/bin/env python3
"""
Commit 进一步筛选脚本 —— Step 1

依次执行以下三步过滤：
  1. 过滤 Type3（无客观评测指标）
  2. 收紧截止日期（默认 2019-01-01；对完全依赖早期 commit 的项目可单独放宽）
     - commons-math / gson: 2017-01-01（这两个项目的非 Type3 commit 全部早于 2019）
  3. 过滤 merge commit 以及超大改动（变更文件数 > MAX_FILES）

用法:
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

# 确保能 import 项目根模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from git import Repo, GitCommandError, InvalidGitRepositoryError
except ImportError:
    print("[ERROR] 请先安装 gitpython: pip install gitpython")
    sys.exit(1)

# ── 默认路径 ──────────────────────────────────────────────────────────────────
DEFAULT_CSV = "/Users/mac/Desktop/TestUpdate/qualified_commits_new.csv"
DEFAULT_PROJECTS_ROOT = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
DEFAULT_OUT = "/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv"
DEFAULT_SINCE = "2019-01-01"
DEFAULT_MAX_FILES = 20

# 项目级别的日期宽松覆盖（这些项目的非 Type3 commit 全部早于 2019，需单独放宽）
PROJECT_DATE_OVERRIDES = {
    "commons-math": datetime(2016, 1, 1),
    "gson":         datetime(2016, 1, 1),
}
# ─────────────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="TUBench commit 第一轮精筛")
    p.add_argument("--csv", default=DEFAULT_CSV, help="输入 CSV 路径")
    p.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT, help="项目根目录")
    p.add_argument("--since", default=DEFAULT_SINCE, help="截止日期（只保留此日期之后）")
    p.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                   help="单 commit 最大变更文件数（含测试+源码+其他）")
    p.add_argument("--out", default=DEFAULT_OUT, help="输出 CSV 路径")
    return p.parse_args()


def load_repos(projects_root: str, projects) -> dict:
    """加载所有需要的 git Repo 对象"""
    repos = {}
    for proj in sorted(projects):
        path = os.path.join(projects_root, proj)
        if not os.path.isdir(path):
            print(f"  [WARN] 项目目录不存在: {path}")
            continue
        try:
            repos[proj] = Repo(path)
        except (InvalidGitRepositoryError, Exception) as e:
            print(f"  [WARN] 无法加载 git 仓库 {proj}: {e}")
    return repos


def resolve_commit(repo: Repo, short_hash: str):
    """将短 hash 解析为完整 commit 对象，失败返回 None"""
    try:
        full = repo.git.rev_parse(short_hash)
        return repo.commit(full)
    except Exception:
        return None


def count_all_changed_files(commit) -> int:
    """统计与父 commit 相比的变更文件总数（所有类型文件）"""
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

    # ── 读取 CSV ──────────────────────────────────────────────────────────────
    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    print(f"\n{'='*55}")
    print(f"  TUBench Commit 精筛 Step-1")
    print(f"{'='*55}")
    print(f"  原始 commit 数       : {total}")

    # ── Step 1: 过滤 Type3 ────────────────────────────────────────────────────
    after_type3 = [r for r in rows if r["Type"].strip().lower() != "type 3"]
    n_type3 = total - len(after_type3)
    print(f"\n[Step 1] 过滤 Type3")
    print(f"  淘汰 Type3           : {n_type3}")
    print(f"  剩余                 : {len(after_type3)}")

    # ── 加载仓库 ─────────────────────────────────────────────────────────────
    all_projects = {r["Project"].strip() for r in after_type3}
    print(f"\n  加载 {len(all_projects)} 个 git 仓库...")
    repos = load_repos(args.projects_root, all_projects)

    # ── Step 2 & 3: 日期 / merge / 文件数 ────────────────────────────────────
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

        # Step 2: 日期过滤（支持项目级别宽松覆盖）
        effective_cutoff = PROJECT_DATE_OVERRIDES.get(proj, date_cutoff)
        if commit_date < effective_cutoff:
            stats["old_date"] += 1
            continue

        # Step 3a: merge commit
        if len(commit.parents) > 1:
            stats["merge"] += 1
            continue

        # Step 3b: 超大改动
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

    # ── 输出统计 ──────────────────────────────────────────────────────────────
    print(f"\n[Step 2] 过滤截止日期 < {args.since}")
    print(f"  淘汰（日期过老）     : {stats['old_date']}")
    print(f"\n[Step 3] 过滤 merge commit 与超大改动（>{args.max_files} 文件）")
    print(f"  淘汰（merge commit） : {stats['merge']}")
    print(f"  淘汰（> {args.max_files} 文件）   : {stats['large_change']}")
    print(f"  淘汰（hash解析失败） : {stats['resolve_fail'] + stats['no_repo']}")

    print(f"\n{'='*55}")
    print(f"  最终剩余 commit 数   : {len(passed)}")
    print(f"{'='*55}")

    # 按项目统计
    by_proj = defaultdict(int)
    by_type = defaultdict(int)
    for r in passed:
        by_proj[r["Project"]] += 1
        by_type[r["Type"]] += 1

    print("\n  各项目剩余分布:")
    for proj, cnt in sorted(by_proj.items()):
        print(f"    {proj:<30} {cnt}")

    print("\n  各 Type 剩余分布:")
    for t, cnt in sorted(by_type.items()):
        print(f"    {t:<20} {cnt}")

    # ── 保存结果 ──────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(args.out), exist_ok=True) if os.path.dirname(args.out) else None
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Project", "Type", "CommitID", "FullHash", "Date", "ChangedFiles"])
        writer.writeheader()
        writer.writerows(passed)

    print(f"\n  结果已保存至: {args.out}\n")


if __name__ == "__main__":
    main()

