import asyncio
import json
import requests_unixsocket
from urllib.parse import quote_plus

DOCKER_SOCKET_PATH = "/var/run/docker.sock"

async def create_exec_instance(container_id: str) -> str:
    print(f"[DEBUG] Creating exec instance for container: {container_id}")
    session = requests_unixsocket.Session()
    url = f"http+unix://{quote_plus(DOCKER_SOCKET_PATH)}/containers/{container_id}/exec"

    # Set TTY + interactive shell prompt using PS1
    exec_config = {
        "AttachStdin": True,
        "AttachStdout": True,
        "AttachStderr": True,
        "Tty": True,
        "Cmd": [
            "/bin/sh",
            "-i",
            "-c",
            'export PS1="\\w # "; exec /bin/sh'
        ]
    }

    print(f"[DEBUG] Exec config: {exec_config}")
    print(f"[DEBUG] POST {url}")
    resp = session.post(url, json=exec_config)
    print(f"[DEBUG] Response status: {resp.status_code}")
    resp.raise_for_status()
    exec_id = resp.json()["Id"]
    print(f"[DEBUG] Exec instance ID: {exec_id}")
    return exec_id

async def open_docker_shell(container_id: str):
    print(f"[DEBUG] Opening docker shell for container: {container_id}")
    exec_id = await create_exec_instance(container_id)
    print(f"[DEBUG] Connecting to Docker socket: {DOCKER_SOCKET_PATH}")
    reader, writer = await asyncio.open_unix_connection(DOCKER_SOCKET_PATH)

    payload = json.dumps({"Detach": False, "Tty": True})
    request = (
        f"POST /v1.41/exec/{exec_id}/start HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(payload)}\r\n"
        f"\r\n"
        f"{payload}"
    )

    print(f"[DEBUG] Sending request to start exec instance:\n{request}")
    writer.write(request.encode())
    await writer.drain()

    # Read and skip HTTP headers
    response_headers = b""
    while True:
        line = await reader.readline()
        if line in (b'\r\n', b''):
            break
        response_headers += line
    print(f"[DEBUG] Skipped response headers:\n{response_headers.decode(errors='ignore')}")

    print(f"[DEBUG] Shell session ready")

    class DebugStreamReader:
        def __init__(self, reader):
            self._reader = reader

        async def read(self, n=-1):
            data = await self._reader.read(n)
            print(f"[DEBUG] [READ] {len(data)} bytes: {data!r}")
            return data

        async def readline(self):
            line = await self._reader.readline()
            print(f"[DEBUG] [READLINE] {line!r}")
            return line

        def at_eof(self):
            return self._reader.at_eof()

    class DebugStreamWriter:
        def __init__(self, writer):
            self._writer = writer

        def write(self, data):
            print(f"[DEBUG] [WRITE] {len(data)} bytes: {data!r}")
            return self._writer.write(data)

        async def drain(self):
            await self._writer.drain()

        def close(self):
            print(f"[DEBUG] [CLOSE] Writer closed")
            self._writer.close()

    return DebugStreamReader(reader), DebugStreamWriter(writer)
