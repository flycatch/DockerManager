from bindings import APP_BINDINGS
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
import time
from datetime import datetime, timedelta


class DockerManager(App):
    CSS_PATH = "../ui.tcss"
    BINDINGS = APP_BINDINGS
    ENABLE_COMMAND_PALETTE = False

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, ContainerCard] = {}
        self.uncategorized_cards: Dict[str, ContainerCard] = {}
        self.projects: dict[str, list[tuple[int, str, str, str, str]]] = {}
        self._refreshing = False
        self.current_project: str | None = None

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

            # Update Uncategorized View
            if "Uncategorized" in all_projects:
                await self.sync_card_list(
                    all_projects["Uncategorized"],
                    self.uncategorized_cards,
                    self.uncategorized_list
                )

            # Update Compose Project Tree
            self.project_tree.root.remove_children()
            self.project_tree.root.allow_expand = False
            for project, containers in all_projects.items():
                if project != "Uncategorized":
                    icon = "🔹"
                    node = self.project_tree.root.add(f"{icon} {project}", data=containers)
                    node.allow_expand = False

            self.project_tree.root.expand()

            # Update currently selected project containers
            if self.current_project and self.project_tree.root.children:
                selected_node = next(
                    (child for child in self.project_tree.root.children if str(child.label.plain if isinstance(child.label, Text) else child.label) == self.current_project),
                    None
                )
                if selected_node:
                    await self.refresh_container_list(selected_node.data or [])

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
        new_ids = {cid for _, cid, *_ in container_data}
        old_ids = set(container_map.keys())

        # Remove cards that no longer exist
        for cid in old_ids - new_ids:
            card = container_map.pop(cid)
            await card.remove()

        # Add or update cards
        for idx, cid, name, image, status in container_data:
            if cid in container_map:
                container_map[cid].update_status(status)
            else:
                card = ContainerCard(idx, cid, name, image, status)
                container_map[cid] = card
                await mount_target.mount(card)

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
            if start_container(focused.container_id):
                self.notify_success(f"Started container: {focused.container_name}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to start container: {focused.container_name}")

    def action_stop_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            if stop_container(focused.container_id):
                self.notify_success(f"Stopped container: {focused.container_name}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to stop container: {focused.container_name}")

    def action_delete_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            if delete_container(focused.container_id):
                self.notify_success(f"Deleted container: {focused.container_name}")
                self.run_worker(self.refresh_projects, exclusive=True, group="refresh")
            else:
                self.notify_error(f"Failed to delete container: {focused.container_name}")

    def action_open_menu(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            self.push_screen(ContainerActionScreen(focused.container_id, focused.container_name))

    async def on_container_action_screen_selected(self, message: ContainerActionScreen.Selected):
        cid = message.container_id
        action = message.action
        
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


