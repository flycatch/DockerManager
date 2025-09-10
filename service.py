# service.py
from __future__ import annotations
from typing import Dict, List, Tuple, Sequence, Optional
import requests_unixsocket
from datetime import datetime

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()

# 7-tuple: (idx, id, name, image, status, ports, created)
ContainerTuple7 = Tuple[int, str, str, str, str, str, str]
# Legacy 5-tuple: (idx, id, name, image, status)
ContainerTuple5 = Tuple[int, str, str, str, str]


def _safe_get_name(container: dict) -> str:
    names = container.get("Names") or []
    if names:
        return str(names[0]).lstrip("/")
    return container.get("Name", "unknown")

def _format_ports(ports_field: Optional[list]) -> str:
    if not ports_field:
        return ""
    
    parts = []
    for p in ports_field:
        if isinstance(p, dict):
            private = p.get("PrivatePort")
            public = p.get("PublicPort")
            proto = p.get("Type", "tcp")
            
            if public is not None:
                parts.append(f"{public}:{private}/{proto}")
            elif private is not None:
                parts.append(f"{private}/{proto}")  # container-only port
    
    # Remove duplicates
    parts = [part for i, part in enumerate(parts) if part not in parts[:i]]
    return ", ".join(parts)



def _format_created(created_value) -> str:
    # Docker returns Created as seconds since epoch (int). But be defensive.
    try:
        ts = int(created_value)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        # If it's already a formatted string or unknown, just return a str
        return str(created_value or "")

def _shorten_image(image: str) -> str:
    """
    Convert a Docker image string to a short, readable form.
    Examples:
      'mysql:8.0'         -> 'mysql:8.0'
      'sha256:1y8948021...' -> 'sha256:1y8948021'
      'nginx@sha256:abcd...' -> 'nginx@sha256:abcd1234'
    """
    if not image:
        return "unknown"
    
    # Truncate long SHA digests
    if "sha256:" in image:
        # keep only first 12 chars of SHA
        parts = image.split(":")
        if len(parts) == 2 and parts[0] == "sha256":
            return f"sha256:{parts[1][:30]}"
        elif "@" in image:  # handle image@sha256:...
            name, digest = image.split("@")
            if digest.startswith("sha256:"):
                return f"{name}@sha256:{digest.split(':')[1][:30]}"
    
    return image


def get_projects_with_containers() -> Dict[str, List[ContainerTuple7]]:
    """
    Returns a mapping of project name -> list of 7-tuples:
      (idx, short_id, name, image, status, ports, created_at)
    This is the canonical (full) shape used across the app.
    """
    try:
        response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})
    except Exception as e:
        return {"Error": [(0, "N/A", "Error", "N/A", f"Request failed: {e}", "N/A", "N/A")]}

    if response.status_code != 200:
        return {"Error": [(0, "N/A", "Error", "N/A", f"HTTP {response.status_code}", "N/A", "N/A")]}

    data = response.json()
    if not data:
        return {"No Projects": [(0, "N/A", "No containers", "", "", "", "")]}

    projects: Dict[str, List[ContainerTuple7]] = {}
    for idx, container in enumerate(data):
        labels = container.get("Labels") or {}
        project = labels.get("com.docker.compose.project", "Uncategorized")

        port_info = _format_ports(container.get("Ports"))
        created_date = _format_created(container.get("Created"))

        short_id = str(container.get("Id", ""))[:12]
        name = _safe_get_name(container)
        image = _shorten_image(str(container.get("Image", "")))
        status = str(container.get("Status", ""))

        container_info: ContainerTuple7 = (
            idx + 1,
            short_id,
            name,
            image,
            status,
            port_info,
            created_date,
        )
        projects.setdefault(project, []).append(container_info)

    return projects


# Backwards-compatible helper (if some code expects the old 5-tuple shape)
def get_projects_with_containers_short() -> Dict[str, List[ContainerTuple5]]:
    full = get_projects_with_containers()
    short_map: Dict[str, List[ContainerTuple5]] = {}
    for project, containers in full.items():
        short_map[project] = [
            (idx, cid, name, image, status)
            for (idx, cid, name, image, status, *_) in containers
        ]
    return short_map


def start_container(container_id: str) -> bool:
    """Start container. Returns True on success (204)."""
    resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/start")
    return resp.status_code == 204


def stop_container(container_id: str, timeout: Optional[int] = None) -> bool:
    """
    Stop container. Returns True if stopped successfully or already stopped.
    Some Docker setups return 304 for 'already stopped' — accept it.
    """
    params = {}
    if timeout is not None:
        params["t"] = timeout
    resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/stop", params=params)
    return resp.status_code in (204, 304)


def delete_container(container_id: str, force: bool = False) -> bool:
    """Delete (remove) a container. Returns True if removed (204) or not found (404)."""
    qs = "?force=true" if force else ""
    resp = session.delete(f"{DOCKER_SOCKET_URL}/containers/{container_id}{qs}")
    return resp.status_code in (204, 404)


# Project-level helpers ------------------------------------------------------

def _get_project_containers(project: str) -> List[str]:
    """Return list of full container IDs belonging to a Compose project (case-insensitive)."""
    try:
        response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})
    except Exception:
        return []

    if response.status_code != 200:
        return []

    containers = response.json()
    project_containers: List[str] = []

    for c in containers:
        labels = c.get("Labels") or {}
        compose_project = labels.get("com.docker.compose.project")
        if not compose_project:
            continue
        if compose_project.strip().lower() == project.strip().lower():
            # Prefer the full ID if available
            full_id = c.get("Id") or (c.get("ID") if "ID" in c else None)
            if full_id:
                project_containers.append(full_id)

    return project_containers


def stop_project(project: str) -> bool:
    containers = _get_project_containers(project)
    if not containers:
        print(f"[ERROR] No containers found for project '{project}'")
        return False

    success = True
    for cid in containers:
        print(f"[DEBUG] Stopping container {cid[:12]}...")
        resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{cid}/stop")
        if resp.status_code not in (204, 304):
            print(f"[ERROR] Failed to stop container {cid[:12]}: HTTP {resp.status_code}")
            success = False
        else:
            print(f"[DEBUG] ✓ Successfully stopped container {cid[:12]}")
    return success


def start_project(project: str) -> bool:
    containers = _get_project_containers(project)
    if not containers:
        print(f"[ERROR] No containers found for project '{project}'")
        return False

    success = True
    for cid in containers:
        print(f"[DEBUG] Starting container {cid[:12]}...")
        resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{cid}/start")
        if resp.status_code != 204:
            print(f"[ERROR] Failed to start container {cid[:12]}: HTTP {resp.status_code}")
            success = False
        else:
            print(f"[DEBUG] ✓ Successfully started container {cid[:12]}")
    return success


def delete_project(project: str, force: bool = True) -> bool:
    containers = _get_project_containers(project)
    if not containers:
        print(f"[ERROR] No containers found for project '{project}'")
        return False

    success = True
    for cid in containers:
        print(f"[DEBUG] Deleting container {cid[:12]}...")
        resp = session.delete(f"{DOCKER_SOCKET_URL}/containers/{cid}", params={"force": str(force).lower()})
        if resp.status_code not in (204, 404):
            print(f"[ERROR] Failed to delete container {cid[:12]}: HTTP {resp.status_code}")
            success = False
        else:
            print(f"[DEBUG] ✓ Successfully deleted container {cid[:12]}")
    return success


def restart_project(project: str) -> bool:
    return stop_project(project) and start_project(project)
