#!/usr/bin/env python3
"""Deploy n8n workflows from JSON definitions to the Orca instance.

Usage:
    python -m pipelines.n8n.deploy                      # deploy all
    python -m pipelines.n8n.deploy email_sync            # deploy one by name
    python -m pipelines.n8n.deploy --list                # list remote workflows
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Load config from .env
# ---------------------------------------------------------------------------


def _load_config() -> tuple[str, str]:
    """Read N8N_BASE_URL and N8N_API_KEY from .env or environment."""
    import os

    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    base_url = os.getenv("N8N_BASE_URL", "").rstrip("/")
    api_key = os.getenv("N8N_API_KEY", "")

    if not base_url or not api_key:
        print("ERROR: N8N_BASE_URL and N8N_API_KEY must be set in .env")
        sys.exit(1)

    return base_url, api_key


# ---------------------------------------------------------------------------
# n8n REST API helpers
# ---------------------------------------------------------------------------


def _headers(api_key: str) -> dict:
    return {"Content-Type": "application/json", "X-N8N-API-KEY": api_key}


def list_workflows(base_url: str, api_key: str) -> list[dict]:
    res = httpx.get(f"{base_url}/api/v1/workflows", headers=_headers(api_key), timeout=15)
    res.raise_for_status()
    return res.json().get("data", [])


def find_workflow_by_name(base_url: str, api_key: str, name: str) -> dict | None:
    for wf in list_workflows(base_url, api_key):
        if wf.get("name") == name:
            return wf
    return None


def create_workflow(base_url: str, api_key: str, definition: dict) -> dict:
    res = httpx.post(
        f"{base_url}/api/v1/workflows",
        headers=_headers(api_key),
        json=definition,
        timeout=30,
    )
    res.raise_for_status()
    return res.json()


def update_workflow(base_url: str, api_key: str, wf_id: str, definition: dict) -> dict:
    res = httpx.put(
        f"{base_url}/api/v1/workflows/{wf_id}",
        headers=_headers(api_key),
        json=definition,
        timeout=30,
    )
    res.raise_for_status()
    return res.json()


def activate_workflow(base_url: str, api_key: str, wf_id: str, active: bool = True) -> dict:
    endpoint = "activate" if active else "deactivate"
    res = httpx.post(
        f"{base_url}/api/v1/workflows/{wf_id}/{endpoint}",
        headers=_headers(api_key),
        timeout=15,
    )
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# Deploy logic
# ---------------------------------------------------------------------------

WORKFLOWS_DIR = Path(__file__).parent / "workflows"


def deploy_workflow(base_url: str, api_key: str, filepath: Path) -> str:
    """Deploy a single workflow JSON file. Creates or updates by name."""
    definition = json.loads(filepath.read_text())
    name = definition.get("name", filepath.stem)
    should_activate = definition.pop("active", True)

    # Remove read-only fields that n8n rejects
    for ro_field in ("id", "tags", "createdAt", "updatedAt", "versionId", "meta"):
        definition.pop(ro_field, None)

    existing = find_workflow_by_name(base_url, api_key, name)

    if existing:
        wf_id = existing["id"]
        update_workflow(base_url, api_key, wf_id, definition)
        activate_workflow(base_url, api_key, wf_id, active=should_activate)
        return f"UPDATED: {name} (id={wf_id})"
    else:
        result = create_workflow(base_url, api_key, definition)
        wf_id = result.get("id", "?")
        if should_activate:
            try:
                activate_workflow(base_url, api_key, wf_id)
            except Exception as e:
                return f"CREATED: {name} (id={wf_id}) — activation failed: {e}"
        return f"CREATED: {name} (id={wf_id})"


def deploy_all(base_url: str, api_key: str, name_filter: str | None = None):
    """Deploy all workflow JSON files from the workflows/ directory."""
    if not WORKFLOWS_DIR.exists():
        print(f"No workflows directory found at {WORKFLOWS_DIR}")
        return

    files = sorted(WORKFLOWS_DIR.glob("*.json"))
    if not files:
        print("No workflow JSON files found")
        return

    if name_filter:
        files = [f for f in files if name_filter in f.stem]
        if not files:
            print(f"No workflow matching '{name_filter}'")
            return

    for filepath in files:
        try:
            result = deploy_workflow(base_url, api_key, filepath)
            print(f"  + {result}")
        except Exception as e:
            print(f"  ! FAILED {filepath.name}: {e}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Deploy n8n workflows to Orca")
    parser.add_argument("name", nargs="?", help="Deploy a specific workflow by name substring")
    parser.add_argument("--list", action="store_true", help="List remote workflows")
    args = parser.parse_args()

    base_url, api_key = _load_config()
    print(f"n8n: {base_url}")

    if args.list:
        workflows = list_workflows(base_url, api_key)
        if not workflows:
            print("  (no workflows)")
        for wf in workflows:
            status = "ACTIVE" if wf.get("active") else "inactive"
            print(f"  [{status}] {wf['name']} (id={wf['id']})")
        return

    print("Deploying workflows...")
    deploy_all(base_url, api_key, args.name)
    print("Done.")


if __name__ == "__main__":
    main()
