# service.py
"""Docker service and container management module.

This module provides high-level functions for interacting with Docker services
and containers. It handles:
- Container listing and grouping
- Service status management
- Container operations (start/stop/delete)
- Data formatting and type safety
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import requests_unixsocket
from datetime import datetime

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()

# 7-tuple: (idx, id, name, image, status, ports, created)
ContainerTuple7 = Tuple[int, str, str, str, str, str, str]
# Legacy 5-tuple: (idx, id, name, image, status)
ContainerTuple5 = Tuple[int, str, str, str, str]


def _safe_get_name(container: dict) -> str:
    """Safely extract container name from container data.
    
    Args:
        container: Container data dictionary from Docker API
        
    Returns:
        str: Container name without leading slash, or 'unknown'
        
    This function handles various Docker API response formats and ensures
    a valid string is always returned.
    """
    names = container.get("Names") or []
    if names:
        return str(names[0]).lstrip("/")
    return container.get("Name", "unknown")

def _format_ports(ports_field: Optional[list]) -> str:
    """Format container port mappings into a readable string.
    
    Args:
        ports_field: List of port mapping dictionaries from Docker API
        
    Returns:
        str: Formatted string of port mappings (e.g., "8080:80/tcp")
        
    The function:
    1. Handles both public and private ports
    2. Includes protocol information
    3. Removes duplicate mappings
    4. Returns empty string for no ports
    """
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
    """Format container creation timestamp into human-readable format.
    
    Args:
        created_value: Unix timestamp or string from Docker API
        
    Returns:
        str: Formatted date string (YYYY-MM-DD HH:MM)
        
    This function safely handles both integer timestamps and
    pre-formatted strings from the Docker API.
    """
    # Docker returns Created as seconds since epoch (int). But be defensive.
    try:
        ts = int(created_value)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        # If it's already a formatted string or unknown, just return a str
        return str(created_value or "")

def _shorten_image(image: str) -> str:
    """Convert a Docker image string to a short, readable form.
    
    Args:
        image: Full Docker image string
        
    Returns:
        str: Shortened and formatted image string
        
    Examples:
        'mysql:8.0'         -> 'mysql:8.0'
        'sha256:1y8948021...' -> 'sha256:1y8948021'
        'nginx@sha256:abcd...' -> 'nginx@sha256:abcd1234'
        
    The function handles various image string formats:
    - Regular tagged images
    - SHA256 digest references
    - Image@digest format
    - Empty or invalid strings
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
    """Get all Docker projects and their containers.
    
    Returns:
        Dict mapping project names to lists of container tuples, where each tuple contains:
        (idx, short_id, name, image, status, ports, created_at)
        
    This is the canonical data format used throughout the application.
    The function:
    1. Retrieves all containers via Docker API
    2. Groups them by project using Compose labels
    3. Formats container details consistently
    4. Handles error cases gracefully
    
    Containers not part of a Compose project are grouped under "Uncategorized".
    Error conditions return an "Error" project with descriptive status.
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
    """Get projects and containers with minimal information.
    
    Returns:
        Dict mapping project names to lists of container tuples, where each tuple contains:
        (idx, container_id, name, image, status)
        
    This is a backwards-compatible version of get_projects_with_containers()
    that returns the legacy 5-tuple format, omitting ports and creation time.
    Used by older parts of the application that haven't been updated to use
    the full 7-tuple format.
    """
    full = get_projects_with_containers()
    short_map: Dict[str, List[ContainerTuple5]] = {}
    for project, containers in full.items():
        short_map[project] = [
            (idx, cid, name, image, status)
            for (idx, cid, name, image, status, *_) in containers
        ]
    return short_map


def start_container(container_id: str) -> bool:
    """Start a Docker container.
    
    Args:
        container_id: ID or name of the container to start
        
    Returns:
        bool: True if container started successfully (HTTP 204)
        
    The function attempts to start a stopped container using the Docker API.
    A return value of True indicates the container was successfully started
    or was already running.
    """
    resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/start")
    return resp.status_code == 204


def stop_container(container_id: str, timeout: Optional[int] = None) -> bool:
    """Stop a Docker container.
    
    Args:
        container_id: ID or name of the container to stop
        timeout: Seconds to wait for container to stop gracefully
        
    Returns:
        bool: True if container stopped successfully or was already stopped
        
    The function handles both normal stop (204) and already-stopped (304) cases.
    If timeout is specified, the container will be forcefully stopped after
    that many seconds if it hasn't stopped gracefully.
    """
    params = {}
    if timeout is not None:
        params["t"] = timeout
    resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/stop", params=params)
    return resp.status_code in (204, 304)


def delete_container(container_id: str, force: bool = False) -> bool:
    """Delete (remove) a Docker container.
    
    Args:
        container_id: ID or name of the container to delete
        force: If True, force remove the container even if running
        
    Returns:
        bool: True if container was removed or didn't exist
        
    The function considers both successful removal (204) and container-not-found (404)
    as successful outcomes since the end result is the same - container doesn't exist.
    Use force=True to remove running containers or when normal removal fails.
    """
    qs = "?force=true" if force else ""
    resp = session.delete(f"{DOCKER_SOCKET_URL}/containers/{container_id}{qs}")
    return resp.status_code in (204, 404)


# Project-level helpers ------------------------------------------------------

def _get_project_containers(project: str) -> List[str]:
    """Get all container IDs for a Docker Compose project.
    
    Args:
        project: Name of the Docker Compose project
        
    Returns:
        list: List of full container IDs belonging to the project
        
    The function:
    1. Queries all containers
    2. Filters by Docker Compose project label
    3. Uses case-insensitive matching
    4. Returns full container IDs for reliability
    
    Returns empty list if project not found or on API errors.
    """
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
    """Stop all containers in a Docker Compose project.
    
    Args:
        project: Name of the Docker Compose project
        
    Returns:
        bool: True if all containers were stopped successfully
        
    The function:
    1. Gets all containers in the project
    2. Attempts to stop each container
    3. Handles already-stopped containers
    4. Logs progress and errors
    5. Returns success only if all containers stopped
    """
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

