import os
import json
import zipfile
import subprocess
from datetime import datetime
from pathlib import Path

root = Path(r"c:\Users\hboora\Repos\ado-pipeline-insight-plug-and-play")
zip_path = root / "webapp-deploy.zip"

if zip_path.exists():
    zip_path.unlink()

# Generate build metadata
try:
    commit_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(root)).decode().strip()
    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root)).decode().strip()
except Exception:
    commit_sha = "unknown"
    branch = "master"

version_data = {
    "version": "1.3.0",
    "git_commit": commit_sha,
    "git_branch": branch,
    "build_timestamp": datetime.utcnow().isoformat() + "Z",
    "service": "ADO Pipeline Insight",
    "environment": "production"
}

version_file = root / "app" / "version.json"
with open(version_file, "w", encoding="utf-8") as f:
    json.dump(version_data, f, indent=2)

print(f"Generated {version_file}: {commit_sha} on {branch}")

def add_dir(zf: zipfile.ZipFile, folder_path: Path, arc_prefix: str):
    for path in folder_path.rglob("*"):
        if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        if path.is_file():
            arcname = str(Path(arc_prefix) / path.relative_to(folder_path)).replace("\\", "/")
            zf.write(path, arcname)

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    # 1. requirements.txt
    req = root / "requirements.txt"
    if req.exists():
        zf.write(req, "requirements.txt")
    
    # 2. app/
    add_dir(zf, root / "app", "app")
    
    # 3. core/
    add_dir(zf, root / "core", "core")
    
    # 4. frontend/dist/
    add_dir(zf, root / "frontend" / "dist", "frontend/dist")

print(f"Created {zip_path}: {zip_path.stat().st_size} bytes")
with zipfile.ZipFile(zip_path, "r") as zf:
    print("Entries count:", len(zf.namelist()))
    for name in zf.namelist()[:15]:
        print("  -", name)
