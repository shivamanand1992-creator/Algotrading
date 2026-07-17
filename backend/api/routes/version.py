"""
Version API - Check which deployment is running
"""
from fastapi import APIRouter
from datetime import datetime
import subprocess

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

    return {
        "version": "1.0.0",
        "commit": commit,
        "branch": branch,
        "deployed_at": "2026-07-17T13:20:00",
        "frontend_build": "hermes-monitor-v2",
        "hermes_monitor_enabled": True,
    }
