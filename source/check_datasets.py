#!/usr/bin/env python3
"""Integration correctness on all prepared distributions and SIMD tail lengths."""
import csv, json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
methods=['heap_scalar','heap_batch','heap_avx2','array_scalar','array_batch','array_avx2','stl']
report=[]
for data in sorted((root/'data').glob('*.csv')):
    meta=json.loads(Path(str(data)+'.json').read_text())
    for k in (1,64,100,128):
        updates=None; checksum=None
        for method in methods:
            cmd=[str(root/'build/topk_bench'),str(data),meta['dtype'],method,str(k),'1','diagnostic']
            r=subprocess.run(cmd,text=True,capture_output=True,check=True)
            row=next(csv.DictReader(r.stdout.splitlines()))
            if checksum is None: checksum=row['checksum']
            if checksum!=row['checksum']: raise AssertionError('cross-method checksum mismatch')
            if method!='stl':
                if updates is None: updates=row['updates']
                if updates!=row['updates']: raise AssertionError('cross-method update count mismatch')
            report.append({'data':data.name,'k':k,'method':method,'status':'pass'})
(root/'build/dataset-checks.json').write_text(json.dumps(report,indent=2))
print(f'PASS {len(report)} dataset/method checks (diagnostic, not timing evidence)')
