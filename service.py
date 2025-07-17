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