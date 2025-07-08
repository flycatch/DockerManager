import requests_unixsocket

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()


def get_containers() -> list[tuple[str, str, str, str]]:
    response = session.get(f"{DOCKER_SOCKET_URL}/containers/json", params={"all": "1"})

    if response.status_code != 200:
        return [("N/A", "Error", "N/A", f"HTTP {response.status_code}")]

    data = response.json()
    if not data:
        return [("N/A", "No containers", "", "")]

    return [
        (
            container["Id"][:12],
            container["Names"][0].strip("/"),
            container["Image"],
            container["Status"],
        )
        for container in data
    ]


def start_container(container_id: str) -> bool:
    response = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/start")
    return response.status_code == 204


def stop_container(container_id: str) -> bool:
    response = session.post(f"{DOCKER_SOCKET_URL}/containers/{container_id}/stop")
    return response.status_code == 204
