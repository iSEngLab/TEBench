#!/usr/bin/env python3
"""
TUBench -- Finer-grained source-change classification (Step 3)

Reads filtered_commits_step2.csv, analyzes the **source-code** diff of every
commit, and assigns one of four mutually-exclusive categories:

  feature_addition  -- New public/protected method(s) added, or significant
                       new code paths inserted into existing methods.
  refactoring       -- Method renamed / moved, parameters reordered / renamed,
                       no semantic change to the overall API contract.
  bug_fix           -- Internal implementation change with no signature change
                       and no new methods; typically corrects wrong logic.
  api_change        -- Return type, parameter type, or 'throws' clause modified
                       on an existing method (breaks source compatibility).

Heuristics are based on unified-diff pattern matching; the script outputs a
new CSV with an added 'ChangeCategory' column.

Usage:
  python analysis/classify_changes.py [--csv PATH] [--projects-root PATH] [--out PATH]
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from git import Repo, InvalidGitRepositoryError

DEFAULT_CSV          = "/Users/mac/Desktop/TestUpdate/filtered_commits_step2.csv"
DEFAULT_PROJECTS_ROOT = "/Users/mac/Desktop/TestUpdate/TUDataset/defects4j-projects"
DEFAULT_OUT          = "/Users/mac/Desktop/TestUpdate/filtered_commits_step3.csv"

SOURCE_PATTERNS = ['src/main/java', 'main/java', 'src/main']

# ── Message-based keyword patterns (primary signal, title-only) ───────────────
_MSG_KEYWORDS: dict[str, list[str]] = {
    'bug_fix': [
        r'\bfix(es|ed|ing)?\b', r'\bbug\b', r'\bincorrect\b',
        r'\bwrong\b', r'\binvalid\b', r'\bnull\b',
        r'\bnpe\b', r'\bfail(ure|s|ed)?\b',
        r"\bdon'?t\s+\w+\b",       # "don't lose", "don't recode"
        r'\bprevent\b', r'\bavoid\b',
        r'\bresolv(e|es|ed)\b', r'\bbroken\b', r'\bregress\b',
        r'\bpatch\b', r'\bworkaround\b',
        r'\bmisuse\b', r'\bleak\b', r'\brace\s+condition\b',
        r'\bshould\s+\w+\s+(return|throw|be)\b',  # "should return true if"
    ],
    'refactoring': [
        r'\brenam(e|es|ed|ing)\b', r'\brefactor\b', r'\bcleanup\b',
        r'\bclean[\s_-]?up\b', r'\breorganis[e]?\b', r'\breorganiz[e]?\b',
        r'\bextract\b', r'\bmov(e|es|ed|ing)\b', r'\bsimplif\b',
        r'\brestructur\b', r'\bsort\b', r'\breorder\b', r'\brearrang\b',
        r'\buse\s+\w+\s+directly\b',   # "Use StandardCharsets directly"
        r'\buse\s+\w+\s+instead\b',    # "use X instead"
        r'\bswitch\s+to\b', r'\breplace\b', r'\bconsolidat\b',
        r'\bimprove\s+(naming|readability|javadoc)\b',
        r'\bremove\s+unused\b', r'\bremove\s+duplicate\b',
        r'\bformat(t?ing)?\b', r'\bwhitespace\b', r'\bindent\b',
        r'\binlin(e|ed|es)\b', r'\bpull[\s_-]?up\b', r'\bpush[\s_-]?down\b',
        r'\bcode[\s_-]?(style|quality|cleanup)\b',
        r'\btoward\s+deprecati',       # "Toward deprecating X" (code cleanup)
        r'\bjavadoc\b',                # "Add missing Javadoc", "Fix Javadoc"
        r'\breuse\b',                  # "Reuse commons-codec"
        r'\bmerge[sd]?\s+\w+\s+(into|with)\b',
    ],
    'api_change': [
        r'\bdeprecat(e|es|ed|ing)\b',          # "Deprecate", "Deprecating"
        r'\bgenerif(y|ied)\b', r'\bgeneric[s]?\b',
        r'\bchange[sd]?\s+\w+\s+to\b',         # "Change X to Y"
        r'\bchange[sd]?\s+(type|return|signature|interface|contract|parameter)\b',
        r'\bmade?\s+\w+\s+return\b',            # "Made X return Y"
        r'\bnow\s+returns?\b',                  # "now returns a string"
        r'\bnow\s+throws?\b',                   # "now throws ArchiveException"
        r'\brather\s+than\s+\w*(exception|error|runtime)\b',
        r'\binstead\s+of\s+\w*(exception|error|runtime)\b',
        r'\bthrows?\s+checked\b',               # "throws checked exceptions"
        r'\bthrows?\s+clause\b',
        r'\bbreak(s|ing)?\s+\w*(api|compat|backward)\b',
        r'\bremove[sd]?\s+\w*(method|api|interface)\b',
        r'\bmigrat(e|es|ed|ing)\b',
        r'\biterator\(\)',                       # "change getBits() to iterator()"
        r'\bflip\s+\w+\s+(args|arguments|param)\b',
        r'\b(return|parameter)\s+type\b',
        r'\bapi\s+(change|update|break|rename)\b',
    ],
    'feature_addition': [
        r'\badd[sed]?\s+support\b',             # "Add support for X"
        r'\badd[sed]?\s+(?!javadoc|\w+\s+javadoc)\w',  # "add X" but not "add javadoc"
        r'\bnew\s+\w',                           # "new X" as first word(s)
        r'\bimplement(s|ed|ing|ation)?\b',
        r'\bintroduc(e|es|ed|ing)\b',
        r'\bcreate[sd]?\b', r'\bprovid(e|es|ed|ing)\b',
        r'\benable[sd]?\b', r'\bextend[sd]?\b',
        r'\ballow[sed]?\s+pass\b',              # "Allow passing X"
        r'\ballow[sed]?\s+\w+\s+to\b',
        r'\binclude[sd]?\b', r'\bfeature\b', r'\benhance\b',
        r'\bexpos(e|es|ed|ing)\b',
    ],
}
_MSG_PAT: dict[str, list[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats]
    for cat, pats in _MSG_KEYWORDS.items()
}

# ── Weights ───────────────────────────────────────────────────────────────────
MSG_W  = 4.0   # weight per keyword match in commit TITLE (first line only)
DIFF_W = 0.3   # weight for diff-derived signals (small vs message)

# ── Java method-signature regex (applied to diff lines) ───────────────────────
_SKIP = {'if', 'while', 'for', 'switch', 'catch', 'return', 'else', 'try', 'new', 'class'}
_MOD  = r'(?:(?:public|protected|private|static|final|abstract|synchronized|native|default)\s+)*'
_TYPE = r'(?:<[^>]+>\s+)?[\w$][\w$.<>, \[\]]+'
_NAME = r'([\w$]+)'
_PAR  = r'\(([^)]*)\)'
METHOD_RE = re.compile(rf'^\s*{_MOD}({_TYPE})\s+{_NAME}\s*{_PAR}\s*(?:throws\s+[\w$., ]+)?\s*(?:\{{|$)')

THROWS_RE   = re.compile(r'\bthrows\b')
DEPRECATED_RE = re.compile(r'@Deprecated')


def is_source_file(path: str) -> bool:
    return path.endswith('.java') and any(p in path for p in SOURCE_PATTERNS)


def _parse_sig(line: str):
    """Return (return_type, name, params) or (None, None, None)."""
    m = METHOD_RE.match(line)
    if m and m.group(2) not in _SKIP:
        return m.group(1).strip(), m.group(2), (m.group(3) or '').strip()
    return None, None, None


def _score_message(msg: str) -> dict[str, float]:
    """Score based on commit title (first line) keywords only -- body is too noisy."""
    title = msg.split('\n')[0].strip().lower()
    scores: dict[str, float] = defaultdict(float)
    for cat, pats in _MSG_PAT.items():
        for pat in pats:
            if pat.search(title):
                scores[cat] += MSG_W
    return scores


def _score_diff(repo: Repo, parent_hash: str, full_hash: str, src_files: list) -> dict[str, float]:
    """Score the four categories based on source-code diff heuristics."""
    scores: dict[str, float] = defaultdict(float)

    for path in src_files:
        try:
            diff = repo.git.diff('-U5', parent_hash, full_hash, '--', path)
        except Exception:
            continue

        added_lines   = [l[1:] for l in diff.split('\n') if l.startswith('+') and not l.startswith('+++')]
        removed_lines = [l[1:] for l in diff.split('\n') if l.startswith('-') and not l.startswith('---')]

        # @Deprecated annotation added -> api_change
        if any(DEPRECATED_RE.search(l) for l in added_lines):
            scores['api_change'] += 2.0 * DIFF_W

        # Parse signatures: (ret_type, name) -> params
        def sigs(lines):
            result = {}
            for l in lines:
                rt, nm, params = _parse_sig(l)
                if nm:
                    result[nm] = (rt, params)
            return result

        added_sigs   = sigs(added_lines)
        removed_sigs = sigs(removed_lines)

        new_methods     = set(added_sigs) - set(removed_sigs)
        deleted_methods = set(removed_sigs) - set(added_sigs)
        modified        = set(added_sigs) & set(removed_sigs)

        # New method names appear -> feature addition (unless balanced by deletes -> rename)
        if new_methods:
            if deleted_methods:
                # Likely rename (refactoring): old name gone, new name appears
                ratio = min(len(new_methods), len(deleted_methods)) / max(len(new_methods), len(deleted_methods))
                scores['refactoring'] += ratio * 3.0 * DIFF_W
                # Surplus new methods are genuinely new
                surplus = len(new_methods) - len(deleted_methods)
                if surplus > 0:
                    scores['feature_addition'] += surplus * 2.0 * DIFF_W
            else:
                scores['feature_addition'] += len(new_methods) * 3.0 * DIFF_W

        # Signature changes on existing methods
        for name in modified:
            old_rt, old_params = removed_sigs[name]
            new_rt, new_params = added_sigs[name]
            old_params_n = re.sub(r'\s+', ' ', old_params)
            new_params_n = re.sub(r'\s+', ' ', new_params)

            ret_changed    = (old_rt != new_rt)
            params_changed = (old_params_n != new_params_n)

            if ret_changed:
                scores['api_change'] += 3.0 * DIFF_W
            elif params_changed:
                # Try to tell parameter type change (API) from name-only change (refactoring)
                old_types = re.sub(r'\b\w+(?=\s*[,)])', '', old_params_n)
                new_types = re.sub(r'\b\w+(?=\s*[,)])', '', new_params_n)
                if old_types != new_types:
                    scores['api_change'] += 2.5 * DIFF_W
                else:
                    scores['refactoring'] += 1.5 * DIFF_W

        # throws-clause changes
        throws_in_added   = any(THROWS_RE.search(l) for l in added_lines)
        throws_in_removed = any(THROWS_RE.search(l) for l in removed_lines)
        if throws_in_added != throws_in_removed:
            scores['api_change'] += 1.5 * DIFF_W

        # No signature lines at all -> body-only change -> bug fix
        if not added_sigs and not removed_sigs:
            scores['bug_fix'] += 4.0 * DIFF_W
        elif modified and not new_methods and not deleted_methods:
            if scores.get('api_change', 0) == 0 and scores.get('refactoring', 0) == 0:
                scores['bug_fix'] += 2.0 * DIFF_W

    return scores


def classify_commit(repo: Repo, full_hash: str) -> str:
    """
    Returns one of: 'feature_addition', 'refactoring', 'bug_fix', 'api_change'
    Uses commit message (primary) + source diff (secondary) scoring.
    """
    try:
        commit = repo.commit(full_hash)
        if not commit.parents:
            return 'bug_fix'
        parent_hash = commit.parents[0].hexsha

        # Primary: commit message
        scores = _score_message(commit.message)

        # Secondary: source diff
        all_files  = repo.git.diff('--name-only', parent_hash, full_hash).splitlines()
        src_files  = [f for f in all_files if is_source_file(f)]
        diff_scores = _score_diff(repo, parent_hash, full_hash, src_files)
        for cat, val in diff_scores.items():
            scores[cat] = scores.get(cat, 0) + val

        if not scores:
            return 'bug_fix'
        return max(scores, key=scores.get)

    except Exception:
        return 'bug_fix'


def parse_args():
    p = argparse.ArgumentParser(description="TUBench commit fine-grained classification Step-3")
    p.add_argument("--csv",           default=DEFAULT_CSV)
    p.add_argument("--projects-root", default=DEFAULT_PROJECTS_ROOT)
    p.add_argument("--out",           default=DEFAULT_OUT)
    return p.parse_args()


def main():
    args = parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding='utf-8')))
    print(f"\n{'='*57}")
    print(f"  TUBench Fine-grained Change Classification Step-3")
    print(f"{'='*57}")
    print(f"  Input commit count: {len(rows)}")

    # Load repos
    projects = {r['Project'].strip() for r in rows}
    repos = {}
    for proj in sorted(projects):
        path = os.path.join(args.projects_root, proj)
        try:
            repos[proj] = Repo(path)
        except Exception:
            print(f"  [WARN] Unable to load repository: {proj}")

    # Classify
    results = []
    cat_counts = defaultdict(int)
    for idx, r in enumerate(rows, 1):
        proj = r['Project'].strip()
        fh   = r.get('FullHash', r.get('CommitID', '')).strip()
        repo = repos.get(proj)
        cat  = classify_commit(repo, fh) if repo else 'bug_fix'
        cat_counts[cat] += 1
        results.append({**r, 'ChangeCategory': cat})
        if idx % 30 == 0:
            print(f"    Progress: {idx}/{len(rows)}")

    # Summary
    total = len(results)
    print(f"\n{'='*57}")
    print(f"  Classification result distribution:")
    LABELS = {
        'feature_addition': 'Feature Addition',
        'refactoring':      'Refactoring    ',
        'bug_fix':          'Bug Fix        ',
        'api_change':       'API Change     ',
    }
    for cat in ['feature_addition', 'refactoring', 'bug_fix', 'api_change']:
        n = cat_counts[cat]
        pct = n / total * 100
        bar = chr(9608) * int(pct / 2)
        print(f"  {LABELS[cat]} ({cat:<18}): {n:>4}  {pct:5.1f}%  {bar}")

    print(f"\n  Type x Category cross-table:")
    tc = defaultdict(lambda: defaultdict(int))
    for r in results:
        tc[r['Type'].strip()][r['ChangeCategory']] += 1
    for t in sorted(tc):
        row_str = '  '.join(
            f"{c}={tc[t][c]}"
            for c in ['feature_addition', 'refactoring', 'bug_fix', 'api_change']
        )
        print(f"    {t}: {row_str}")

    # Save
    fieldnames = list(rows[0].keys()) + ['ChangeCategory']
    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(results)
    print(f"\n  Results saved to: {args.out}\n")


if __name__ == '__main__':
    main()
