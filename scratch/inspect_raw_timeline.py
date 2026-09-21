import sys
import json
sys.path.insert(0, ".")
from core.ado_client import AzureDevOpsClient
from core.config import get_ado_pat

def main():
    org = "cicd-analysis"
    project = "project-1"
    pat = get_ado_pat(org)
    client = AzureDevOpsClient(org, pat)
    timeline = client.get_timeline(project, 1)
    records = timeline.get("records", [])
    print(f"Total timeline records for run 1: {len(records)}")
    for r in records:
        print(f"id={r.get('id')} parentId={r.get('parentId')} type={r.get('type')} name={r.get('name')} order={r.get('order')} start={r.get('startTime')} finish={r.get('finishTime')}")

if __name__ == '__main__':
    main()
