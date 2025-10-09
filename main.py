"""Docker Manager Terminal UI Application.

This is the main entry point for the Docker Manager TUI application.
It provides a terminal-based interface for managing Docker containers
and services with an intuitive, keyboard-driven interface.

Features:
- Container management (start/stop/delete)
- Service orchestration
- Container logs and shell access
- Real-time updates
- Search and filtering
"""

from managers.docker_manager import DockerManager

if __name__ == "__main__":
    DockerManager().run(mouse=False)

    