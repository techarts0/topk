#!/usr/bin/env python3
"""Prepare a real chronological score stream from the NYC TLC January 2024 Parquet."""
import argparse, csv, hashlib, json, math, subprocess, sys
from pathlib import Path
import duckdb
URL='https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet'
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--n',type=int,default=100003)
    p.add_argument('--out',default='data/nyc_yellow_2024_01_distance_chrono_100003.csv')
    a=p.parse_args()
    if a.n<=0: p.error('n > 0 required')
    root=Path(__file__).resolve().parent
    raw=root/'data/yellow_tripdata_2024-01.parquet';raw.parent.mkdir(parents=True,exist_ok=True)
    out=root/a.out if not Path(a.out).is_absolute() else Path(a.out)
    if out.exists() or Path(str(out)+'.json').exists(): p.error('refusing to overwrite output')
    if not raw.exists():
        tmp=Path(str(raw)+'.part')
        subprocess.run(['curl','--fail','--location','--retry','2','--max-time','300',URL,'-o',str(tmp)],check=True)
        tmp.rename(raw)
    con=duckdb.connect();con.execute('SET threads=1')
    sql="""WITH numbered AS (
       SELECT row_number() OVER () AS file_pos, tpep_pickup_datetime AS ts,
              trip_distance AS score FROM read_parquet(?)
       WHERE tpep_pickup_datetime >= TIMESTAMP '2024-01-01'
         AND tpep_pickup_datetime < TIMESTAMP '2024-02-01'
         AND trip_distance > 0 AND isfinite(trip_distance)
     ) SELECT score FROM numbered ORDER BY ts, file_pos LIMIT ?"""
    rows=con.execute(sql,[str(raw),a.n]).fetchall()
    if len(rows)!=a.n: raise RuntimeError(f'only {len(rows)} qualifying records')
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['score']);w.writerows(rows)
    vals=[v[0] for v in rows]
    info={'kind':'real_nyc_taxi','dtype':'float64','n_actual':len(vals),'source_url':URL,
      'source_page':'https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page',
      'source_sha256':sha(raw),'sha256':sha(out),'query':sql,'duckdb':duckdb.__version__,
      'score':'trip_distance, miles as recorded; values >0 and finite',
      'ordering':'pickup timestamp ascending, source file position for ties; not IID',
      'filter':'pickup in January 2024; positive finite distance; first n after chronological sort',
      'duplicate_fraction':1-len(set(vals))/len(vals),'generator_sha256':sha(__file__),
      'source_note':'NYC TLC states data accuracy is not guaranteed; measurement source only',
      'status':'prepared; not confirmatory evidence'}
    Path(str(out)+'.json').write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps({k:info[k] for k in ['n_actual','source_sha256','sha256','duplicate_fraction']}))
if __name__=='__main__': main()
