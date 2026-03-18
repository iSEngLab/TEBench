import csv
from collections import defaultdict

step1 = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step1.csv')))
full  = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step2_full.csv')))
final = list(csv.DictReader(open('/Users/mac/Desktop/TestUpdate/filtered_commits_step2.csv')))

print("=== STEP 1 STATS (490 commits) ===")
by_proj = defaultdict(int)
by_type = defaultdict(int)
years_s1 = []
for r in step1:
    by_proj[r['Project']] += 1
    by_type[r['Type'].strip()] += 1
    d = r.get('Date', '')
    if d: years_s1.append(int(d[:4]))
print(f"Projects ({len(by_proj)}):")
for p, c in sorted(by_proj.items()):
    print(f"  {p}: {c}")
print(f"Type dist: {dict(by_type)}")
print(f"Year range: {min(years_s1)}-{max(years_s1)}")

print("\n=== STEP2 FULL STATS (314 commits) ===")
by_proj2 = defaultdict(int)
by_cat2 = defaultdict(int)
by_diff2 = defaultdict(int)
by_type2 = defaultdict(int)
test_lines2, src_lines2, years2 = [], [], []
for r in full:
    by_proj2[r['Project']] += 1
    by_cat2[r['TestChangeType']] += 1
    by_diff2[r['Difficulty']] += 1
    by_type2[r['Type'].strip()] += 1
    test_lines2.append(int(r['TestChangedLines'] or 0))
    src_lines2.append(int(r['SrcChangedLines'] or 0))
    d = r.get('Date', '')
    if d: years2.append(int(d[:4]))
print(f"Projects ({len(by_proj2)}):")
for p, c in sorted(by_proj2.items()):
    print(f"  {p}: {c}")
print(f"Category dist: {dict(by_cat2)}")
print(f"Difficulty dist: {dict(by_diff2)}")
print(f"Type dist: {dict(by_type2)}")
test_lines2.sort(); src_lines2.sort(); n2 = len(test_lines2)
print(f"TestChangedLines: min={test_lines2[0]}, p25={test_lines2[n2//4]}, median={test_lines2[n2//2]}, p75={test_lines2[3*n2//4]}, max={test_lines2[-1]}, mean={sum(test_lines2)/n2:.1f}")
print(f"SrcChangedLines:  min={src_lines2[0]}, p25={src_lines2[n2//4]}, median={src_lines2[n2//2]}, p75={src_lines2[3*n2//4]}, max={src_lines2[-1]}, mean={sum(src_lines2)/n2:.1f}")

print("\n=== FINAL DATASET STATS (161 commits) ===")
by_projF = defaultdict(int)
by_catF = defaultdict(int)
by_diffF = defaultdict(int)
by_typeF = defaultdict(int)
test_linesF, src_linesF, yearsF, cf_list = [], [], [], []
for r in final:
    by_projF[r['Project']] += 1
    by_catF[r['TestChangeType']] += 1
    by_diffF[r['Difficulty']] += 1
    by_typeF[r['Type'].strip()] += 1
    test_linesF.append(int(r['TestChangedLines'] or 0))
    src_linesF.append(int(r['SrcChangedLines'] or 0))
    cf_list.append(int(r['ChangedFiles'] or 0))
    d = r.get('Date', '')
    if d: yearsF.append(int(d[:4]))
print(f"Projects ({len(by_projF)}):")
for p, c in sorted(by_projF.items()):
    print(f"  {p}: {c}")
print(f"Category dist: {dict(by_catF)}")
print(f"Difficulty dist: {dict(by_diffF)}")
print(f"Type dist: {dict(by_typeF)}")
test_linesF.sort(); src_linesF.sort(); cf_list.sort(); n = len(test_linesF)
print(f"TestChangedLines: min={test_linesF[0]}, p25={test_linesF[n//4]}, median={test_linesF[n//2]}, p75={test_linesF[3*n//4]}, max={test_linesF[-1]}, mean={sum(test_linesF)/n:.1f}")
print(f"SrcChangedLines:  min={src_linesF[0]}, p25={src_linesF[n//4]}, median={src_linesF[n//2]}, p75={src_linesF[3*n//4]}, max={src_linesF[-1]}, mean={sum(src_linesF)/n:.1f}")
print(f"ChangedFiles:     min={cf_list[0]}, p25={cf_list[n//4]}, median={cf_list[n//2]}, p75={cf_list[3*n//4]}, max={cf_list[-1]}, mean={sum(cf_list)/n:.1f}")
year_cnt = defaultdict(int)
for y in yearsF: year_cnt[y] += 1
print("\nYear distribution:")
for y in sorted(year_cnt): print(f"  {y}: {year_cnt[y]}")
print(f"Year range: {min(yearsF)}-{max(yearsF)}, Median year: {sorted(yearsF)[n//2]}")
mc = sorted([len([m for m in r['ChangedTestMethods'].split('|') if m]) for r in final])
print(f"\nChanged test methods per commit: min={mc[0]}, median={mc[n//2]}, max={mc[-1]}, mean={sum(mc)/n:.1f}")

