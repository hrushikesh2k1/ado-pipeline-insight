import sys
sys.path.insert(0, ".")
from backend.app.core.db import fetch_all

def main():
    tables = ['pipelines', 'pipeline_runs', 'pipeline_stages', 'pipeline_jobs', 'pipeline_tasks']
    for t in tables:
        cols = fetch_all(f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='{t}'")
        print(f"=== {t} ===")
        for c in cols:
            print(f"  {c['COLUMN_NAME']} ({c['DATA_TYPE']})")

if __name__ == '__main__':
    main()
