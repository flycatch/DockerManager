
from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import base64
import io
import os
import stat as statlib
import tarfile
import json
import requests_unixsocket
from datetime import datetime
import time

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()

# 7-tuple: (idx, id, name, image, status, ports, created)
ContainerTuple7 = Tuple[int, str, str, str, str, str, str]
# Legacy 5-tuple: (idx, id, name, image, status)
ContainerTuple5 = Tuple[int, str, str, str, str]
ImageTuple6 = Tuple[int, str, str, str, str, str]


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
        (idx, full_id, name, image, status, ports, created_at)
        
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

        container_id = str(container.get("Id", ""))
        name = _safe_get_name(container)
        image = _shorten_image(str(container.get("Image", "")))
        status = str(container.get("Status", ""))

        container_info: ContainerTuple7 = (
            idx + 1,
            container_id,
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


def get_container_state(container_id: str) -> str | None:
    """Return the Docker state status for a container, e.g. running/exited."""
    try:
        resp = session.get(f"{DOCKER_SOCKET_URL}/containers/{container_id}/json")
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    payload = resp.json() or {}
    state = payload.get("State") or {}
    status = state.get("Status")
    return str(status).lower() if status else None


def wait_for_container_state(container_id: str, target_state: str, timeout: float = 8.0) -> bool:
    """Poll Docker until the container reaches the target state or timeout expires."""
    deadline = time.monotonic() + timeout
    target = target_state.strip().lower()
    while time.monotonic() < deadline:
        current_state = get_container_state(container_id)
        if current_state == target:
            return True
        time.sleep(0.25)
    return False


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

def restart_container(container_id: str, timeout: Optional[int] = None) -> bool:
    """Restart a Docker container (stop then start).
    Args:
        container_id: ID or name of the container to restart
        timeout: Seconds to wait for container to stop gracefully
    Returns:
        bool: True if container restarted successfully
    """
    stopped = stop_container(container_id, timeout)
    started = start_container(container_id)
    return stopped and started


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


def get_images() -> List[ImageTuple6]:
    """Return Docker images for the top-level images tab."""
    try:
        response = session.get(f"{DOCKER_SOCKET_URL}/images/json", params={"all": "1"})
    except Exception:
        return []
    if response.status_code != 200:
        return []
    container_counts = _get_container_counts_by_image_id()

    images = response.json() or []
    rows: List[ImageTuple6] = []
    for idx, image in enumerate(images, start=1):
        image_id = str(image.get("Id") or "")
        tags = image.get("RepoTags") or []
        digests = image.get("RepoDigests") or []
        reference = _pick_image_reference(tags, digests, image_id)
        size = _bytes_to_human_image(int(image.get("Size") or 0))
        created = _format_created(image.get("Created"))
        containers = str(container_counts.get(image_id, 0))
        rows.append((idx, image_id, reference, size, created, containers))
    return rows


def get_image_info_dict(image_ref: str) -> dict[str, str]:
    """Fetch detailed image information for the image info tab."""
    try:
        response = session.get(f"{DOCKER_SOCKET_URL}/images/{image_ref}/json")
    except Exception as exc:
        return {"Error:": f"Failed to fetch image info: {exc}"}
    if response.status_code != 200:
        return {"Error:": f"Failed to fetch image info (HTTP {response.status_code})"}

    payload = response.json() or {}
    config = payload.get("Config") or {}
    rootfs = payload.get("RootFS") or {}
    metadata = payload.get("Metadata") or {}

    repo_tags = payload.get("RepoTags") or []
    repo_digests = payload.get("RepoDigests") or []
    exposed_ports = sorted((config.get("ExposedPorts") or {}).keys())
    env_list = config.get("Env") or []
    cmd = " ".join(config.get("Cmd") or []) or "<default>"
    entrypoint = " ".join(config.get("Entrypoint") or []) or "<default>"
    labels = config.get("Labels") or {}

    return {
        "Reference:": _pick_image_reference(repo_tags, repo_digests, str(payload.get("Id") or "")),
        "Image ID:": str(payload.get("Id") or "")[:19],
        "Created:": str(payload.get("Created") or ""),
        "Size:": _bytes_to_human_image(int(payload.get("Size") or 0)),
        "Virtual Size:": _bytes_to_human_image(int(payload.get("VirtualSize") or 0)),
        "OS / Arch:": f"{payload.get('Os') or 'unknown'} / {payload.get('Architecture') or 'unknown'}",
        "Author:": str(payload.get("Author") or "<unknown>"),
        "User:": str(config.get("User") or "<default>"),
        "Working Dir:": str(config.get("WorkingDir") or "<none>"),
        "Entrypoint:": entrypoint,
        "Command:": cmd,
        "Env Vars:": str(len(env_list)),
        "Exposed Ports:": ", ".join(exposed_ports) if exposed_ports else "none",
        "Tags:": ", ".join(repo_tags) if repo_tags else "none",
        "Digests:": ", ".join(repo_digests) if repo_digests else "none",
        "Labels:": str(len(labels)),
        "RootFS Type:": str(rootfs.get("Type") or "unknown"),
        "RootFS Layers:": str(len(rootfs.get("Layers") or [])),
        "Last Tag Time:": str(metadata.get("LastTagTime") or "unknown"),
    }


def create_temp_container_for_image(image_ref: str) -> str | None:
    """Create and start a temporary container for image filesystem browsing."""
    shell_attempts = [
        ["/bin/sh", "-lc", "while true; do sleep 3600; done"],
        ["sh", "-lc", "while true; do sleep 3600; done"],
        ["/busybox/sh", "-lc", "while true; do sleep 3600; done"],
    ]
    for cmd in shell_attempts:
        body = {
            "Image": image_ref,
            "Entrypoint": [cmd[0]],
            "Cmd": cmd[1:],
            "Labels": {
                "codex.image_fs_temp": "true",
                "codex.image_ref": image_ref,
            },
            "AttachStdin": False,
            "AttachStdout": False,
            "AttachStderr": False,
            "Tty": False,
            "NetworkDisabled": True,
        }
        try:
            response = session.post(f"{DOCKER_SOCKET_URL}/containers/create", json=body)
        except Exception:
            continue
        if response.status_code != 201:
            continue
        payload = response.json() or {}
        container_id = str(payload.get("Id") or "")
        if not container_id:
            continue
        try:
            started = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/start")
        except Exception:
            remove_container(container_id)
            continue
        if started.status_code == 204 and wait_for_container_state(container_id, "running", timeout=4.0):
            return container_id
        remove_container(container_id)
    return None


def remove_container(container_id: str) -> bool:
    try:
        response = session.delete(
            f"{DOCKER_SOCKET_URL}/containers/{container_id}",
            params={"force": "1"},
        )
    except Exception:
        return False
    return response.status_code in (204, 404)


def remove_image_temp_containers(image_ref: str) -> None:
    try:
        response = session.get(
            f"{DOCKER_SOCKET_URL}/containers/json",
            params={"all": "1", "filters": json.dumps({"label": [f"codex.image_ref={image_ref}", "codex.image_fs_temp=true"]})},
        )
    except Exception:
        return
    if response.status_code != 200:
        return
    for container in response.json() or []:
        container_id = str(container.get("Id") or "")
        if container_id:
            remove_container(container_id)


def remove_all_image_temp_containers() -> None:
    try:
        response = session.get(
            f"{DOCKER_SOCKET_URL}/containers/json",
            params={"all": "1", "filters": json.dumps({"label": ["codex.image_fs_temp=true"]})},
        )
    except Exception:
        return
    if response.status_code != 200:
        return
    for container in response.json() or []:
        container_id = str(container.get("Id") or "")
        if container_id:
            remove_container(container_id)


def list_container_filesystem(container_id: str, path: str) -> tuple[str, list[dict[str, object]], str | None]:
    exec_result = _exec_list_directory(container_id, path)
    if exec_result is not None:
        return exec_result
    """List immediate entries for a path inside a container filesystem."""
    try:
        response = session.get(
            f"{DOCKER_SOCKET_URL}/containers/{container_id}/archive",
            params={"path": path},
        )
    except Exception as exc:
        return "error", [], f"Failed to browse filesystem: {exc}"
    if response.status_code != 200:
        return "error", [], f"Failed to browse filesystem (HTTP {response.status_code})"

    stat_info = _decode_archive_stat(response.headers.get("X-Docker-Container-Path-Stat"))
    kind = _path_kind(stat_info)
    if kind == "file":
        return "file", [], None

    try:
        archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:*")
    except Exception as exc:
        return "error", [], f"Failed to parse filesystem archive: {exc}"

    entries: dict[str, dict[str, object]] = {}
    root_name = str(stat_info.get("name") or "").strip("/")

    with archive:
        for member in archive.getmembers():
            rel_name = _archive_relative_name(member.name, root_name)
            if not rel_name:
                continue
            first_part = rel_name.split("/", 1)[0]
            child_path = _join_container_path(path, first_part)
            entry = entries.get(first_part)
            inferred_dir = "/" in rel_name or member.isdir()
            if entry is None:
                entries[first_part] = {
                    "name": first_part,
                    "path": child_path,
                    "is_dir": inferred_dir,
                    "size": int(member.size or 0),
                }
            elif inferred_dir:
                entry["is_dir"] = True

    ordered = sorted(entries.values(), key=lambda item: (not bool(item["is_dir"]), str(item["name"])))
    return "dir", ordered, None


def read_container_file_preview(container_id: str, path: str, limit: int = 32768) -> str:
    exec_preview = _exec_file_preview(container_id, path, limit)
    if exec_preview is not None:
        return exec_preview
    """Read a text preview for a file inside a container filesystem."""
    try:
        response = session.get(
            f"{DOCKER_SOCKET_URL}/containers/{container_id}/archive",
            params={"path": path},
        )
    except Exception as exc:
        return f"Failed to read file: {exc}"
    if response.status_code != 200:
        return f"Failed to read file (HTTP {response.status_code})"

    try:
        archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:*")
    except Exception as exc:
        return f"Failed to parse file archive: {exc}"

    with archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read(limit + 1)
            if b"\x00" in data:
                return f"Binary file: {path}"
            text = data[:limit].decode("utf-8", errors="replace")
            if len(data) > limit:
                text += "\n\n[truncated]"
            return text or "<empty file>"
    return f"Unable to preview file: {path}"


def _pick_image_reference(tags: list[str], digests: list[str], image_id: str) -> str:
    if tags:
        first = next((tag for tag in tags if tag and tag != "<none>:<none>"), tags[0])
        return str(first)
    if digests:
        return str(digests[0])
    short_id = image_id.split(":")[-1][:12] if image_id else "unknown"
    return f"sha256:{short_id}"


def _bytes_to_human_image(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.2f}{unit}"
        size /= 1024.0
    return f"{int(value)}B"


def _decode_archive_stat(header_value: str | None) -> dict[str, object]:
    if not header_value:
        return {}
    try:
        padding = "=" * (-len(header_value) % 4)
        decoded = base64.urlsafe_b64decode(header_value + padding)
        import json

        payload = json.loads(decoded.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _path_kind(stat_info: dict[str, object]) -> str:
    mode = int(stat_info.get("mode") or 0)
    if statlib.S_ISDIR(mode):
        return "dir"
    if statlib.S_ISREG(mode):
        return "file"
    return "dir"


def _archive_relative_name(member_name: str, root_name: str) -> str:
    normalized = member_name.strip().lstrip("./").lstrip("/")
    if not normalized:
        return ""
    if root_name and normalized == root_name:
        return ""
    if root_name and normalized.startswith(root_name + "/"):
        return normalized[len(root_name) + 1 :]
    return normalized


def _join_container_path(parent: str, child: str) -> str:
    if parent == "/":
        return f"/{child}"
    return os.path.join(parent, child).replace("\\", "/")


def _get_container_counts_by_image_id() -> dict[str, int]:
    try:
        response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})
    except Exception:
        return {}
    if response.status_code != 200:
        return {}
    counts: dict[str, int] = {}
    for container in response.json() or []:
        labels = container.get("Labels") or {}
        if labels.get("codex.image_fs_temp") == "true":
            continue
        image_id = str(container.get("ImageID") or "")
        if image_id:
            counts[image_id] = counts.get(image_id, 0) + 1
    return counts




def _exec_in_container(container_id: str, cmd: list[str]) -> tuple[int | None, str | None]:
    body = {
        "AttachStdout": True,
        "AttachStderr": True,
        "Cmd": cmd,
        "Tty": False,
    }
    try:
        create_resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/exec", json=body)
    except Exception:
        return None, None
    if create_resp.status_code != 201:
        return None, None
    exec_id = str((create_resp.json() or {}).get("Id") or "")
    if not exec_id:
        return None, None
    try:
        start_resp = session.post(
            f"{DOCKER_SOCKET_URL}/exec/{exec_id}/start",
            json={"Detach": False, "Tty": False},
        )
        inspect_resp = session.get(f"{DOCKER_SOCKET_URL}/exec/{exec_id}/json")
    except Exception:
        return None, None
    if start_resp.status_code != 200 or inspect_resp.status_code != 200:
        return None, None
    exit_code = (inspect_resp.json() or {}).get("ExitCode")
    try:
        output = start_resp.content.decode("utf-8", errors="replace")
    except Exception:
        output = ""
    return int(exit_code) if exit_code is not None else None, output


def _exec_list_directory(container_id: str, path: str) -> tuple[str, list[dict[str, object]], str | None] | None:
    script = (
        'p="$1"; '
        'if [ -d "$p" ]; then printf "__KIND__:dir\\n"; ls -1Ap "$p"; '
        'elif [ -f "$p" ]; then printf "__KIND__:file\\n"; '
        'else printf "__KIND__:error\\n"; exit 2; fi'
    )
    for shell in ("/bin/sh", "sh", "/busybox/sh"):
        exit_code, output = _exec_in_container(container_id, [shell, "-lc", script, "_", path])
        if exit_code is None:
            continue
        lines = output.splitlines()
        if not lines:
            return None
        marker = lines[0].strip()
        if marker == "__KIND__:file":
            return "file", [], None
        if marker == "__KIND__:dir":
            entries: list[dict[str, object]] = []
            for raw_name in lines[1:]:
                name = raw_name.strip()
                if not name:
                    continue
                is_dir = name.endswith("/")
                clean_name = name[:-1] if is_dir else name
                entries.append(
                    {
                        "name": clean_name,
                        "path": _join_container_path(path, clean_name),
                        "is_dir": is_dir,
                        "size": 0,
                    }
                )
            entries.sort(key=lambda item: (not bool(item["is_dir"]), str(item["name"])))
            return "dir", entries, None
        if marker == "__KIND__:error":
            return "error", [], f"Path not found: {path}"
        if exit_code == 0:
            return None
    return None


def _exec_file_preview(container_id: str, path: str, limit: int) -> str | None:
    script = (
        'p="$1"; '
        'if [ ! -f "$p" ]; then exit 2; fi; '
        f'head -c {int(limit)} "$p"'
    )
    for shell in ("/bin/sh", "sh", "/busybox/sh"):
        exit_code, output = _exec_in_container(container_id, [shell, "-lc", script, "_", path])
        if exit_code is None:
            continue
        if exit_code == 0:
            return output or "<empty file>"
        if exit_code == 2:
            return f"Unable to preview file: {path}"
    return None
