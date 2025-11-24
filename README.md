# Textual DockerManager

A terminal UI for managing Docker containers and Compose services built with Textual (a modern TUI framework for Python).

This project provides a focused workflow for viewing, filtering, and operating on containers and Compose services from your terminal. It emphasizes fast keyboard navigation, unobtrusive notifications, and useful container actions (start/stop/restart, logs, and an interactive shell).

## Why Textual?

Textual is a modern TUI framework that uses rich for styling and rendering. It allows building responsive terminal applications with a widget model similar to GUI frameworks, including:

- Declarative layout and CSS-like styling
- Widgets, containers and focus management
- Key bindings and modal screens
- Smooth scrolling and live updates

Textual makes it easy to build an ergonomic, keyboard-driven Docker manager that feels fast and native in the terminal.

## Why DockerManager?

This project focuses on the common developer/admin tasks you perform on containers:

- Quickly scan running/stopped containers
- Filter/search containers by name, image or status
- Operate on containers (start / stop / restart) with confirmations
- Tail and filter container logs in-place
- Open a shell inside a container
- Manage Docker Compose projects and inspect their containers

It's a handy lightweight alternative to opening a browser or remembering many docker CLI flags when you just need quick inspection and control.

## Features

- Two main tabs: `Standalone` (individual containers) and `Services` (Docker Compose projects)
- Fast incremental search (container or image modes) and status filtering
- Live container status updates with optimized UI refreshes
- Per-container modal screen with: Info, Logs (live tail + filter), and Terminal
- Confirmations for destructive actions and small loading overlays for long-running ops
- Configurable styling via `tcss/` files

## Keybindings

Below are the primary, verified keybindings implemented in the code (these are the defaults shipped in the app):

### Global
- Left / Right: switch to previous / next tab
- Ctrl+Q: quit the application
- Escape: context-aware close/clear behavior

### Containers tab (Standalone / Lists)
- Down / Up: move focus between visible container cards
- Enter: open the Container Action modal for the selected container
- c: open container search (searches container name / id / status)
- i: open image search (searches image name / tag)
- f: toggle status filter dropdown (All / Running / Restarting / Stopped)
- Escape: clear active search or close filter

### Projects tab (Services)
- Arrow keys: navigate the project tree
- Enter (on a project): load and focus that project's container list
- Tab: toggles focus between tree and container list (same as global Tab behavior)
- Down / Up: move between projects in the tree
- Enter: open project actions (or select the project)
- u: Start / bring up the selected project (`start_project`)
- d: Stop the selected project (`stop_project`)
- r: Restart the selected project (`restart_project`)
- /: Focus project search input
- Escape: clear/close project search

### Container Action Modal (per-container overlay)
- Tabs inside the modal: Info, Logs, Terminal (use left/right to switch)
- u: Start the container (confirmation shown)
- d: Stop the container (confirmation shown)
- r: Restart the container (confirmation shown)
- / (when on Logs): focus the logs filter input
- n / N (when on Logs): next / previous match for log filter
- Escape: close the modal and restore app key bindings

### Notes
- The app updates global bindings while a container modal is open so that u/d/r and log shortcuts are available. Bindings are restored when the modal is closed.
- Many list and focus behaviors are context-sensitive (for instance, Escape tries to clear search first).

## Install & Run

### Requirements
- Python 3.10+
- Docker (to actually inspect and operate real containers)

Install dependencies:

```bash
python3 -m pip install -r requirement.txt
```

Run the app from the project root:

```bash
python3 main.py
```

By default `main.py` runs the app with `mouse=False`. To enable mouse support, modify `main.py` to call `DockerManager().run()` without the `mouse=False` argument.

## Project layout (quick)

- `main.py` — app entrypoint
- `managers/docker_manager.py` — the main Textual App subclass, tab switching, background refresh
- `tabs/` — UI tabs: `container_tab.py`, `project_tab.py`, `container_info.py`
- `cards/` — visual components like `container_card.py` and `container_header.py`
- `container_action_menu.py` — modal screen for container actions (Info / Logs / Terminal)
- `service.py` — the small service layer that calls Docker / Compose operations (used by the manager)
- `tcss/` — Textual CSS files for styling

## Developer notes

- Key bindings are defined in `managers/docker_manager.py`, `tabs/container_tab.py`, and `container_action_menu.py`. If you change bindings programmatically, make sure to test their interaction with modal screens (the modal temporarily replaces the app BINDINGS to expose container-specific shortcuts).
- UI styling lives in `tcss/`. Small tweaks there can change layout, spacing and colors.
- Refresh behavior: the app polls the `get_projects_with_containers()` service on an interval and uses a snapshot diff strategy to avoid full UI rebuilds when only statuses change.

## Contributing

Contributions are welcome. Open an issue or PR with a clear description, and include a short demo GIF or recorded terminal session if the change affects UI/UX.

## License

This repository includes a `LICENSE` file — follow its terms when using or contributing.

---
