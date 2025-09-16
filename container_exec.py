# container_exec.py
"""Docker container shell execution module.

This module provides functionality for interacting with Docker containers through shell sessions.
It handles:
- Shell availability checking in containers
- Creating and managing exec instances
- Establishing interactive shell sessions
- Error handling and fallback mechanisms

The module uses Unix socket communication with the Docker daemon and supports
various shell types (sh, bash) with fallback mechanisms for minimal containers.
"""

import asyncio
import json
import requests_unixsocket
from urllib.parse import quote_plus
from typing import Tuple
from asyncio import StreamReader, StreamWriter


DOCKER_SOCKET_PATH = "/var/run/docker.sock"

import asyncio
import json
import requests_unixsocket
from urllib.parse import quote_plus
from typing import Tuple
from asyncio import StreamReader, StreamWriter


DOCKER_SOCKET_PATH = "/var/run/docker.sock"

async def check_shell_availability(container_id: str) -> bool:
    """Check if a container has a shell available.
    
    Args:
        container_id: Docker container ID or name
        
    Returns:
        bool: True if shell is available, False otherwise
        
    This function verifies shell availability by:
    1. Checking if container exists and is running
    2. Attempting a test command execution
    3. Validating command execution works properly
    """
    try:
        session = requests_unixsocket.Session()
        url = f"http+unix://{quote_plus(DOCKER_SOCKET_PATH)}/containers/{container_id}/json"
        
        resp = session.get(url)
        if resp.status_code != 200:
            return False
            
        container_info = resp.json()
        
        # Check if container is running
        if not container_info.get("State", {}).get("Running", False):
            return False
            
        # Try to find a shell in the container
        # First check if we can execute commands directly
        exec_url = f"http+unix://{quote_plus(DOCKER_SOCKET_PATH)}/containers/{container_id}/exec"
        
        # Try a simple command to see if the container responds
        exec_config = {
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "Cmd": ["sh", "-c", "echo 'test'"]
        }
        
        exec_resp = session.post(exec_url, json=exec_config)
        if exec_resp.status_code == 201:
            exec_id = exec_resp.json()["Id"]
            
            # Try to start the exec to see if it works
            start_url = f"http+unix://{quote_plus(DOCKER_SOCKET_PATH)}/exec/{exec_id}/start"
            start_resp = session.post(start_url, json={"Detach": False, "Tty": False})
            
            # If we get a 200, the container can execute commands
            return start_resp.status_code == 200
            
    except Exception as e:
        print(f"Error checking shell availability: {e}")
        
    return False

async def create_exec_instance(container_id: str) -> str:
    """Create an exec instance in the container with shell access.
    
    Args:
        container_id: Docker container ID or name
        
    Returns:
        str: Exec instance ID for the created shell session
        
    Raises:
        Exception: If no shell could be created in the container
        
    The function tries multiple shell types in sequence:
    1. Standard shell (/bin/sh -i)
    2. Bash shell (/bin/bash -i)
    3. Basic sh (sh -i)
    4. Fallback minimal shell execution
    """
    session = requests_unixsocket.Session()
    url = f"http+unix://{quote_plus(DOCKER_SOCKET_PATH)}/containers/{container_id}/exec"

    # Try different approaches to get a shell
    shell_configs = [
        # Try standard shell
        {
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
            "Cmd": ["/bin/sh", "-i"]
        },
        # Try bash
        {
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
            "Cmd": ["/bin/bash", "-i"]
        },
        # Try just sh
        {
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
            "Cmd": ["sh", "-i"]
        },
        # Try with a simple command that might work in minimal containers
        {
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
            "Cmd": ["/bin/sh", "-c", "exec /bin/sh"]
        }
    ]

    for config in shell_configs:
        try:
            resp = session.post(url, json=config)
            if resp.status_code in (200, 201):
                exec_id = resp.json()["Id"]
                return exec_id
        except Exception:
            continue
            
    # If all else fails, try a basic approach
    try:
        basic_config = {
            "AttachStdin": True,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": True,
            "Cmd": ["sh"]
        }
        resp = session.post(url, json=basic_config)
        if resp.status_code in (200, 201):
            return resp.json()["Id"]
    except Exception:
        pass
        
    raise Exception("Could not create exec instance - no shell available")


async def open_docker_shell(container_id: str) -> Tuple[StreamReader, StreamWriter]:
    """Open an interactive shell session with a Docker container.
    
    Args:
        container_id: Docker container ID or name
        
    Returns:
        tuple: StreamReader and StreamWriter for shell I/O
        
    Raises:
        Exception: With descriptive message if shell connection fails
        
    This function:
    1. Creates an exec instance for shell access
    2. Establishes bidirectional connection
    3. Sets up proper TTY handling
    4. Provides detailed error messages on failure
    """
    try:
        exec_id = await create_exec_instance(container_id)
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

        writer.write(request.encode())
        await writer.drain()

        # Read and skip HTTP headers
        while True:
            line = await reader.readline()
            if line in (b'\r\n', b''):
                break

        return reader, writer
        
    except Exception as e:
        # Provide more helpful error messages
        if "no such file or directory" in str(e).lower():
            raise Exception("No shell available in this container")
        elif "container not found" in str(e).lower():
            raise Exception("Container not found")
        elif "is not running" in str(e).lower():
            raise Exception("Container is not running")
        else:
            raise Exception(f"Failed to connect to container: {str(e)}")