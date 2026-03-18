import csv
from collections import defaultdict

full = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step2_full.csv')))
n = len(full)
print(f"Total: {n} commits")

# Project distribution
by_proj = defaultdict(int)
for r in full:
    by_proj[r['Project']] += 1
print("\n--- Project distribution ---")
for p, c in sorted(by_proj.items()):
    print(f"  {p}: {c}  ({c/n*100:.1f}%)")
print(f"  Total projects: {len(by_proj)}")

# Semantic category
by_cat = defaultdict(int)
for r in full:
    by_cat[r['TestChangeType']] += 1
print("\n--- Semantic category distribution ---")
for cat in ('test_breaking', 'test_stale', 'test_missing'):
    print(f"  {cat}: {by_cat[cat]}  ({by_cat[cat]/n*100:.1f}%)")

# Difficulty
by_diff = defaultdict(int)
for r in full:
    by_diff[r['Difficulty']] += 1
print("\n--- Difficulty distribution ---")
for d in ('easy', 'medium', 'hard'):
    print(f"  {d}: {by_diff[d]}  ({by_diff[d]/n*100:.1f}%)")

# Type 1 / Type 2
by_type = defaultdict(int)
for r in full:
    by_type[r['Type'].strip()] += 1
print("\n--- Type 1 / Type 2 ---")
for t, c in sorted(by_type.items()):
    print(f"  {t}: {c}  ({c/n*100:.1f}%)")

# Year distribution
by_year = defaultdict(int)
for r in full:
    d = r.get('Date', '')
    if d:
        by_year[d[:4]] += 1
print("\n--- Year distribution ---")
for y in sorted(by_year):
    print(f"  {y}: {by_year[y]}")
years_list = sorted([int(d[:4]) for r in full for d in [r.get('Date','')] if d])
print(f"  Range: {min(years_list)}-{max(years_list)}, Median year: {sorted(years_list)[n//2]}")

# Quantitative stats
tl, sl, cf, mc = [], [], [], []
for r in full:
    tl.append(int(r['TestChangedLines'] or 0))
    sl.append(int(r['SrcChangedLines'] or 0))
    cf.append(int(r['ChangedFiles'] or 0))
    mc.append(len([m for m in r['ChangedTestMethods'].split('|') if m]))

tl.sort(); sl.sort(); cf.sort(); mc.sort()
print("\n--- Quantitative stats ---")
print(f"TestChangedLines: min={tl[0]}, p25={tl[n//4]}, median={tl[n//2]}, p75={tl[3*n//4]}, max={tl[-1]}, mean={sum(tl)/n:.1f}")
print(f"SrcChangedLines:  min={sl[0]}, p25={sl[n//4]}, median={sl[n//2]}, p75={sl[3*n//4]}, max={sl[-1]}, mean={sum(sl)/n:.1f}")
print(f"ChangedFiles:     min={cf[0]}, p25={cf[n//4]}, median={cf[n//2]}, p75={cf[3*n//4]}, max={cf[-1]}, mean={sum(cf)/n:.1f}")
print(f"ChangedTestMethods: min={mc[0]}, p25={mc[n//4]}, median={mc[n//2]}, p75={mc[3*n//4]}, max={mc[-1]}, mean={sum(mc)/n:.1f}")

# Cross-tabulation: project x category
print("\n--- Project x TestChangeType ---")
proj_cat = defaultdict(lambda: defaultdict(int))
for r in full:
    proj_cat[r['Project']][r['TestChangeType']] += 1
print(f"  {'Project':<26} {'Breaking':>9} {'Stale':>7} {'Missing':>8} {'Total':>6}")
for p in sorted(proj_cat):
    b = proj_cat[p]['test_breaking']
    s = proj_cat[p]['test_stale']
    m = proj_cat[p]['test_missing']
    print(f"  {p:<26} {b:>9} {s:>7} {m:>8} {b+s+m:>6}")

# Cross-tabulation: project x difficulty
print("\n--- Project x Difficulty ---")
proj_diff = defaultdict(lambda: defaultdict(int))
for r in full:
    proj_diff[r['Project']][r['Difficulty']] += 1
print(f"  {'Project':<26} {'Easy':>6} {'Medium':>8} {'Hard':>6} {'Total':>6}")
for p in sorted(proj_diff):
    e = proj_diff[p]['easy']
    m = proj_diff[p]['medium']
    h = proj_diff[p]['hard']
    print(f"  {p:<26} {e:>6} {m:>8} {h:>6} {e+m+h:>6}")

