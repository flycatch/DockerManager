import requests_unixsocket


DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()

def get_projects_with_containers() -> dict[str, list[tuple[int, str, str, str, str]]]:
    response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})
    if response.status_code != 200:
        return {"Error": [(0, "N/A", "Error", "N/A", f"HTTP {response.status_code}")]}

    data = response.json()
    if not data:
        return {"No Projects": [(0, "N/A", "No containers", "", "")]}

    projects: dict[str, list[tuple[int, str, str, str, str]]] = {}
    for idx, container in enumerate(data):
        labels = container.get("Labels", {})
        project = labels.get("com.docker.compose.project", "Uncategorized")
        container_info = (
            idx + 1,
            container["Id"][:12],
            container["Names"][0].strip("/"),
            container["Image"],
            container["Status"],
        )
        projects.setdefault(project, []).append(container_info)

    return projects

def start_container(container_id: str) -> bool:
    response = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/start")
    return response.status_code == 204


def stop_container(container_id: str) -> bool:
    response = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/stop")
    return response.status_code == 204


def delete_container(container_id: str) -> bool:
    response = session.delete(f"{DOCKER_SOCKET_URL}/containers/{container_id}")
    return response.status_code == 204




def stop_project(project: str) -> bool:
    """Stop all containers belonging to a Docker Compose project."""
    containers = _get_project_containers(project)
    if not containers:
        print(f"[ERROR] No containers found for project '{project}'")
        return False
    
    success = True
    for cid in containers:
        print(f"[DEBUG] Stopping container {cid[:12]}...")
        resp = session.post(f"{DOCKER_SOCKET_URL}/containers/{cid}/stop")
        if resp.status_code not in (204, 304):  # 304 = already stopped
            print(f"[ERROR] Failed to stop container {cid[:12]}: HTTP {resp.status_code}")
            success = False
        else:
            print(f"[DEBUG] ✓ Successfully stopped container {cid[:12]}")
    
    return success

def start_project(project: str) -> bool:
    """Start all containers belonging to a Docker Compose project."""
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

def delete_project(project: str) -> bool:
    """Remove all containers belonging to a Docker Compose project."""
    containers = _get_project_containers(project)
    if not containers:
        print(f"[ERROR] No containers found for project '{project}'")
        return False
    
    success = True
    for cid in containers:
        print(f"[DEBUG] Deleting container {cid[:12]}...")
        resp = session.delete(f"{DOCKER_SOCKET_URL}/containers/{cid}?force=true")
        if resp.status_code not in (204, 404):  # 404 = already gone
            print(f"[ERROR] Failed to delete container {cid[:12]}: HTTP {resp.status_code}")
            success = False
        else:
            print(f"[DEBUG] ✓ Successfully deleted container {cid[:12]}")
    
    return success


def restart_project(project: str) -> bool:
    """Restart all containers in the project (stop + start)."""
    return stop_project(project) and start_project(project)


def _get_project_containers(project: str) -> list[str]:
    """Helper: return list of container IDs for a given Compose project."""
    response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})
    if response.status_code != 200:
        print(f"[ERROR] Failed to get containers: HTTP {response.status_code}")
        return []
    
    containers = response.json()
    project_containers = []
    
    print(f"[DEBUG] Looking for project: '{project}'")
    
    for c in containers:
        labels = c.get("Labels") or {}
        
        # ONLY look for the correct label format
        compose_project = labels.get("com.docker.compose.project")
        
        if compose_project:
            # Debug: show what we found
            print(f"[DEBUG] Found container '{c['Names'][0]}' with project: '{compose_project}'")
            
            # Case-insensitive comparison and strip whitespace
            if compose_project.strip().lower() == project.strip().lower():
                print(f"[DEBUG] ✓ Match found! Adding container: {c['Id'][:12]}")
                project_containers.append(c["Id"])
    
    print(f"[DEBUG] Found {len(project_containers)} containers for project '{project}'")
    return project_containers
