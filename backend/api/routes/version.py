"""
Version API - Check which deployment is running
"""
from fastapi import APIRouter
from datetime import datetime
from pathlib import Path
import subprocess
import os

router = APIRouter(prefix="/api", tags=["version"])

@router.get("/version")
async def get_version():
    """Get current deployment version and git commit"""
    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode('ascii').strip()
    except:
        commit = "unknown"
        branch = "unknown"

    # Check if frontend build actually exists
    frontend_build_path = Path(__file__).parent.parent.parent.parent / "frontend" / "build"
    frontend_index = frontend_build_path / "index.html"

    frontend_status = {
        "build_dir_exists": frontend_build_path.exists(),
        "index_html_exists": frontend_index.exists(),
        "build_path": str(frontend_build_path),
    }

    if frontend_build_path.exists():
        try:
            frontend_status["build_files"] = [f.name for f in frontend_build_path.iterdir()][:20]
            frontend_status["build_dir_size_mb"] = sum(
                f.stat().st_size for f in frontend_build_path.rglob('*') if f.is_file()
            ) / (1024 * 1024)
        except:
            pass

    return {
        "version": "1.0.0",
        "commit": commit,
        "branch": branch,
        "deployed_at": datetime.now().isoformat(),
        "frontend_build": "hermes-monitor-v3",
        "hermes_monitor_enabled": True,
        "frontend_status": frontend_status,
        "cwd": os.getcwd(),
    }
