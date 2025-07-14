# container_exec.py

import json
import requests_unixsocket
from typing import Generator

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()


def run_exec_shell(container_id: str) -> Generator[str, None, None]:
    # Step 1: Create exec instance
    create_url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/exec"
    exec_config = {
        "AttachStdin": False,
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "Cmd": ["/bin/sh"],
    }
    create_resp = session.post(create_url, json=exec_config)
    if create_resp.status_code != 201:
        yield f"[ERROR] Failed to create exec: {create_resp.text}"
        return

    exec_id = create_resp.json()["Id"]

    # Step 2: Start exec
    start_url = f"{DOCKER_SOCKET_URL}/exec/{exec_id}/start"
    start_config = {
        "Detach": False,
        "Tty": True,
        "AttachStdin": False
    }
    headers = {"Content-Type": "application/json"}
    start_resp = session.post(start_url, headers=headers, data=json.dumps(start_config), stream=True)

    if start_resp.status_code != 200:
        yield f"[ERROR] Exec start failed: {start_resp.text}"
        return

    try:
        for chunk in start_resp.iter_lines(decode_unicode=True):
            if chunk:
                print("🧪 chunk:", chunk)
                yield chunk
    except Exception as e:
        yield f"[ERROR] Exception: {e}"
