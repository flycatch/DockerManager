"""Docker container logs streaming module.

This module provides functionality to stream logs from Docker containers in real-time.
It handles log streaming with configurable parameters like follow mode, timestamps,
and selective stream targeting (stdout/stderr).

The module uses Unix socket communication with the Docker daemon to efficiently
stream logs with minimal memory overhead through generator-based iteration.
"""

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
    """Stream logs from a Docker container.

    Args:
        container_id: Docker container ID or name
        follow: If True, stream logs continuously
        stdout: Include stdout stream
        stderr: Include stderr stream
        tail: Number of lines to show from the end ("all" or a number)
        timestamps: Include timestamps in output
        since: Show logs since timestamp (Unix epoch)
        until: Show logs before timestamp (Unix epoch)

    Returns:
        Generator yielding log lines as they become available

    The function handles:
    1. Connection to Docker daemon via Unix socket
    2. Docker's multiplexed log format decoding
    3. UTF-8 decoding with error handling
    4. Streaming with minimal memory usage
    """
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
