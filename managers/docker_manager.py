from textual.binding import Binding
from typing import Dict, Any
from textual.app import ComposeResult, App
from textual.widgets import Static, TabbedContent, TabPane, Tree, Footer
from textual.containers import Vertical, Horizontal
from rich.text import Text
from cards.container_card import ContainerCard
from container_action_menu import ContainerActionScreen
from service import (
    get_projects_with_containers,
    start_container,
    stop_container,
    delete_container,
    start_project, stop_project, delete_project, restart_project

)


class DockerManager(App):
    CSS_PATH = "../ui.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("down", "focus_next", "Next Container"),
        ("up", "focus_previous", "Previous Container"),
        ("enter", "open_menu", "Container Actions"),
        ("u", "start_project", "Project Up/Start"),
        ("o", "stop_project", "Project Down/Stop"),
        ("r", "restart_project", "Restart Project"),
        ("x", "delete_project", "Delete Project"),
    ]
    ENABLE_COMMAND_PALETTE = False

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, ContainerCard] = {}
        self.uncategorized_cards: Dict[str, ContainerCard] = {}
        self.projects: dict[str, list[tuple[int, str, str, str, str]]] = {}
        self._refreshing = False
        self.current_project: str | None = None
        self._last_focused_id: str | None = None  # Add this line
        self._last_containers: dict[str, tuple[str, str, str, str]] = {}  # NEW: snapshot {id: (name, image, status)}

    def compose(self) -> ComposeResult:

        with TabbedContent():
            with TabPane("🟡 All Containers", id="tab-uncategorized"):
                self.uncategorized_list = Vertical(id="uncategorized-list")
                yield self.uncategorized_list

            with TabPane("🟢 Compose Projects", id="tab-projects"):
                with Horizontal(id="projects-layout"):
                    self.project_tree = Tree("🔹Compose Projects", id="project-tree")
                    self.container_list = Vertical(id="container-list")
                    yield self.project_tree
                    yield self.container_list

        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(2.0, self.trigger_background_refresh)
        await self.refresh_projects()

    def trigger_background_refresh(self) -> None:
        self.run_worker(self.refresh_projects, exclusive=True, group="refresh")


    async def refresh_projects(self):
        if self._refreshing:
            return
        self._refreshing = True

        try:
            all_projects = get_projects_with_containers()

            # Flatten into a {cid: (name, image, status)} dict for comparison
            new_snapshot = {}
            for project, containers in all_projects.items():
                for _, cid, name, image, status in containers:
                    new_snapshot[cid] = (name, image, status)

            # --- CASE 1: Only statuses changed ---
            if (
                set(new_snapshot.keys()) == set(self._last_containers.keys())
                and all(new_snapshot[cid][0:2] == self._last_containers[cid][0:2] 
                        for cid in new_snapshot)
            ):
                # Just update statuses (faster, no UI rebuild)
                for cid, (name, image, status) in new_snapshot.items():
                    card = self.get_container_card_by_id(cid)
                    if card:
                        card.update_status(status)
                self._last_containers = new_snapshot
                return

            # --- CASE 2: Projects/membership changed → full sync ---
            self._last_containers = new_snapshot

            # Update Uncategorized View
            if "Uncategorized" in all_projects:
                await self.sync_card_list(
                    all_projects["Uncategorized"],
                    self.uncategorized_cards,
                    self.uncategorized_list
                )

            # Rebuild Compose Project Tree
            self.project_tree.root.remove_children()
            self.project_tree.root.allow_expand = False
            for project, containers in all_projects.items():
                if project != "Uncategorized":
                    node = self.project_tree.root.add(f"🔹 {project}", data=containers)
                    node.allow_expand = False
            self.project_tree.root.expand()

            # Auto-select current/first project
            if self.current_project:
                for node in self.project_tree.root.children:
                    label = node.label.plain if isinstance(node.label, Text) else str(node.label)
                    if label[1:].strip() == self.current_project:
                        self.project_tree.select_node(node)
                        await self.refresh_container_list(node.data or [])
                        break
            elif self.project_tree.root.children:
                first_node = self.project_tree.root.children[0]
                self.project_tree.select_node(first_node)
                await self.refresh_container_list(first_node.data or [])

        finally:
            self._refreshing = False

    async def refresh_container_list(self, containers: list[tuple[int, str, str, str, str]]):
        await self.sync_card_list(containers, self.cards, self.container_list)

    async def sync_card_list(
        self,
        container_data: list[tuple[int, str, str, str, str]],
        container_map: dict[str, ContainerCard],
        mount_target: Vertical
    ):
        current_focused = self.screen.focused
        # Add type check before accessing container_id
        focused_id = getattr(current_focused, 'container_id', None) if (current_focused and isinstance(current_focused, ContainerCard)) else None
        
        new_ids = {cid for _, cid, *_ in container_data}
        old_ids = set(container_map.keys())

        # Remove cards that no longer exist
        for cid in old_ids - new_ids:
            card = container_map.pop(cid)
            await card.remove()

        # Create a mapping of container ID to status for quick lookup
        status_map = {cid: status for _, cid, _, _, status in container_data}

        # Update existing cards
        for cid in old_ids & new_ids:
            if cid in container_map and cid in status_map:
                container_map[cid].update_status(status_map[cid])

        # Add new cards
        for idx, cid, name, image, status in container_data:
            if cid not in container_map:
                card = ContainerCard(idx, cid, name, image, status)
                container_map[cid] = card
                await mount_target.mount(card)

        # Restore focus if the focused container still exists
        if focused_id:
            focused_card = self.get_container_card_by_id(focused_id)
            if focused_card:
                self.set_focus(focused_card)
        elif mount_target.children:
            # Focus on first container if available and no previous focus
            self.set_focus(mount_target.children[0])

    def get_container_card_by_id(self, container_id: str) -> ContainerCard | None:
        """Find a container card by ID in either cards dictionary"""
        if container_id in self.cards:
            return self.cards[container_id]
        if container_id in self.uncategorized_cards:
            return self.uncategorized_cards[container_id]
        return None

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        containers: Any = event.node.data
        if containers:
            await self.refresh_container_list(containers)

        # Use the same logic as get_selected_project() for consistency
        self.current_project = self.get_selected_project()

    def action_focus_next(self):
        self.screen.focus_next()
        self.query_one("#container-list").scroll_visible()

    def action_focus_previous(self):
        self.screen.focus_previous()
        self.query_one("#container-list").scroll_visible()

    def action_start_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            container_id = focused.container_id
            if start_container(container_id):
                self.notify_success(f"Started container: {focused.container_name}")
                # Store the ID to restore focus after refresh
                self._last_focused_id = container_id
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to start container: {focused.container_name}")

    def action_stop_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            container_id = focused.container_id
            if stop_container(container_id):
                self.notify_success(f"Stopped container: {focused.container_name}")
                self._last_focused_id = container_id
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to stop container: {focused.container_name}")

    def action_delete_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            container_id = focused.container_id
            container_name = focused.container_name
            if delete_container(container_id):
                self.notify_success(f"Deleted container: {container_name}")
                # Don't try to restore focus for deleted containers
                self._last_focused_id = None
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to delete container: {container_name}")

    def action_open_menu(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            self.push_screen(ContainerActionScreen(focused.container_id, focused.container_name))

    async def on_container_action_screen_selected(self, message: ContainerActionScreen.Selected):
        cid = message.container_id
        action = message.action
        self.disabled = False
        # Get the container name from your cards dictionary
        container_name = "Unknown"
        for card in list(self.cards.values()) + list(self.uncategorized_cards.values()):
            if card.container_id == cid:
                container_name = card.container_name
                break

        success = False
        notification_message = ""
        
        if action == "start":
            success = start_container(cid)
            notification_message = f"Started container: {container_name}" if success else f"Failed to start container: {container_name}"
        elif action == "stop":
            success = stop_container(cid)
            notification_message = f"Stopped container: {container_name}" if success else f"Failed to stop container: {container_name}"
        elif action == "delete":
            success = delete_container(cid)
            notification_message = f"Deleted container: {container_name}" if success else f"Failed to delete container: {container_name}"
        elif action == "logs":
            # Handle logs view
            pass

        if action != "logs" and notification_message:
            if success:
                self.notify_success(notification_message)
            else:
                self.notify_error(notification_message)

        await self.refresh_projects()
        self.set_timer(0.05, lambda: self.run_worker(self.refresh_projects, exclusive=True, group="refresh"))
    
    def get_selected_project(self) -> str | None:
        """Return the currently selected project name from the tree."""
        if self.project_tree and self.project_tree.cursor_node:
            label = self.project_tree.cursor_node.label
            
            # Extract the raw label text
            if isinstance(label, Text):
                raw_label = label.plain.strip()
            else:
                raw_label = str(label).strip()
            
            # Remove the first character (the icon) and any leading/trailing whitespace
            if raw_label and len(raw_label) > 1:
                return raw_label[1:].strip()  # Remove first char and trim
            return raw_label
        return None

    def action_start_project(self):
        project = self.current_project or self.get_selected_project()
        if project:
            if start_project(project):
                self.notify_success(f"Started project: {project}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to start project: {project}")
        else:
            self.notify_warning("No project selected")
            self.app.bell()

    def action_stop_project(self):
        project = self.current_project or self.get_selected_project()
        if project:
            if stop_project(project):
                self.notify_success(f"Stopped project: {project}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to stop project: {project}")
        else:
            self.notify_warning("No project selected")
            self.app.bell()

    def action_delete_project(self):
        project = self.current_project or self.get_selected_project()
        if project:
            if delete_project(project):
                self.notify_success(f"Deleted project: {project}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to delete project: {project}")
        else:
            self.notify_warning("No project selected")
            self.app.bell()

    def action_restart_project(self):
        project = self.current_project or self.get_selected_project()
        if project:
            if restart_project(project):
                self.notify_success(f"Restarted project: {project}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to restart project: {project}")
        else:
            self.notify_warning("No project selected")
            self.app.bell()

    def notify_success(self, message: str) -> None:
        """Show a success notification."""
        self.notify(message, severity="information", timeout=3)

    def notify_error(self, message: str) -> None:
        """Show an error notification."""
        self.notify(message, severity="error", timeout=5)

    def notify_warning(self, message: str) -> None:
        """Show a warning notification."""
        self.notify(message, severity="warning", timeout=4)
