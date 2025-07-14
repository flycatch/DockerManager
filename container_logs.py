import requests_unixsocket
from typing import Generator

DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()


def stream_logs(
    container_id: str,
    follow: bool = False,
    stdout: bool = True,
    stderr: bool = True,
    tail: str = "100",
    timestamps: bool = False,
    since: int = 0,
    until: int = 0,
) -> Generator[str, None, None]:
    params = {
        "follow": str(follow).lower(),
        "stdout": str(stdout).lower(),
        "stderr": str(stderr).lower(),
        "tail": tail,
        "timestamps": str(timestamps).lower(),
    }

    if since:
        params["since"] = str(since)
    if until:
        params["until"] = str(until)

    url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/logs"
    response = session.get(url, params=params, stream=True)

    if response.status_code != 200:
        yield f"[ERROR] HTTP {response.status_code} while fetching logs."
        return

    # Docker multiplexed format: 8-byte header + content
    for chunk in response.iter_lines(decode_unicode=False):
        if chunk:
            line = chunk[8:] if len(chunk) > 8 else chunk
            try:
                yield line.decode("utf-8", errors="ignore")
            except Exception:
                yield "<decode error>"
