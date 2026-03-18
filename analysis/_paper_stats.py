import csv
from collections import defaultdict

final = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step2.csv')))
step1 = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv')))
full  = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step2_full.csv')))

print("=== FINAL DATASET (161 commits) ===")
yc = defaultdict(int)
tl, sl, cf, mc = [], [], [], []
for r in final:
    yc[r['Date'][:4]] += 1
    tl.append(int(r['TestChangedLines'] or 0))
    sl.append(int(r['SrcChangedLines'] or 0))
    cf.append(int(r['ChangedFiles'] or 0))
    mc.append(len([m for m in r['ChangedTestMethods'].split('|') if m]))

tl.sort(); sl.sort(); cf.sort(); mc.sort(); n = len(tl)
print('Year distribution:')
for y in sorted(yc):
    print(f'  {y}: {yc[y]}')
print(f'Year range: {min(yc)} - {max(yc)}, median year: {sorted(yc.keys())[len(yc)//2]}')
print(f'TestLines: min={tl[0]}, p25={tl[n//4]}, median={tl[n//2]}, p75={tl[3*n//4]}, max={tl[-1]}, mean={sum(tl)/n:.1f}')
print(f'SrcLines:  min={sl[0]}, p25={sl[n//4]}, median={sl[n//2]}, p75={sl[3*n//4]}, max={sl[-1]}, mean={sum(sl)/n:.1f}')
print(f'Files:     min={cf[0]}, p25={cf[n//4]}, median={cf[n//2]}, p75={cf[3*n//4]}, max={cf[-1]}, mean={sum(cf)/n:.1f}')
print(f'Methods:   min={mc[0]}, p25={mc[n//4]}, median={mc[n//2]}, p75={mc[3*n//4]}, max={mc[-1]}, mean={sum(mc)/n:.1f}')

print("\n=== STEP1 (490 commits) year distribution ===")
yc1 = defaultdict(int)
by_proj1 = defaultdict(int)
by_type1 = defaultdict(int)
for r in step1:
    yc1[r['Date'][:4]] += 1
    by_proj1[r['Project']] += 1
    by_type1[r['Type'].strip()] += 1
for y in sorted(yc1):
    print(f'  {y}: {yc1[y]}')
print(f'Projects in step1: {len(by_proj1)}')
for p, c in sorted(by_proj1.items()):
    print(f'  {p}: {c}')
print(f'Type dist step1: {dict(by_type1)}')

print("\n=== FULL (314 commits after dedup) ===")
by_cat314 = defaultdict(int)
by_diff314 = defaultdict(int)
for r in full:
    by_cat314[r['TestChangeType']] += 1
    by_diff314[r['Difficulty']] += 1
print(f'Category: {dict(by_cat314)}')
print(f'Difficulty: {dict(by_diff314)}')

