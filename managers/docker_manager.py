from textual.binding import Binding
from typing import Dict, Any, Optional
from textual.app import ComposeResult, App
from textual.widgets import TabbedContent, TabPane, Tree, Footer, Input
from textual.containers import Vertical
from textual.widgets import TabbedContent
from rich.text import Text
from cards.container_card import ContainerCard
from container_action_menu import ContainerActionScreen
from service import (
    get_projects_with_containers,
    start_container,
    stop_container,
    delete_container,
)
from tabs.container_tab import ContainersTab
from tabs.project_tab import ProjectsTab
from cards.container_header import ContainerHeader

class DockerManager(App):
    CSS_PATH = ["../tcss/ui.tcss", "../tcss/header.tcss"]
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("1", "goto_uncategorized", "Standalone", show=True),
        Binding("2", "goto_projects", "Services", show=True),
        Binding("q", "quit", "Quit", show=True)
    ]

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, ContainerCard] = {}
        self.uncategorized_cards: Dict[str, ContainerCard] = {}
        self.projects: dict[str, list[tuple[int, str, str, str, str, str, str]]] = {}
        self._refreshing = False
        self.current_project: str | None = None
        self._last_focused_id: str | None = None
        self._last_containers: dict[str, tuple[str, str, str, str]] = {}

    def compose(self) -> ComposeResult:
        tabbed_content = TabbedContent()
        self.tabbed_content = tabbed_content
        with tabbed_content:
            # --- All Containers tab ---
            with TabPane("🟡 Standalone", id="tab-uncategorized"):
                self.uncategorized_list = ContainersTab(id="uncategorized-list")
                yield self.uncategorized_list

            # --- Projects tab ---
            with TabPane("🟢 Services", id="tab-projects"):
                with ProjectsTab(id="projects-layout"):
                    self.project_tree = Tree("🔹Compose Projects", id="project-tree")
                    yield self.project_tree
                    with Vertical(id="container-section"):
                        yield ContainerHeader()
                        self.container_list = Vertical(id="container-list")
                        yield self.container_list

        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(2.0, self.trigger_background_refresh)
        await self.refresh_projects()
        self.set_focus(self.tabbed_content)

    def _get_tabbed(self) -> TabbedContent:
        return self.query_one(TabbedContent)
    
    def key_escape(self) -> None:
        """Handle Escape key globally - but let focused widgets handle it first."""
        # Check if we're in the uncategorized tab and search is active
        if (not self.is_projects_tab_active() and 
            hasattr(self, 'uncategorized_list') and 
            self.uncategorized_list and 
            self.uncategorized_list.search_active):
            # Let the ContainersTab handle the escape key
            return
        
        # Handle other escape logic for projects tab if needed
        if self.is_projects_tab_active():
            pass

    def action_goto_uncategorized(self) -> None:
        self.tabbed_content.active = "tab-uncategorized"
        if self.uncategorized_list:
            # Focus the first container card, not the search input
            cards = self.uncategorized_list.query(ContainerCard)
            if cards:
                self.set_focus(cards.first())
                self.uncategorized_list.selected_index = 0

    def action_goto_projects(self) -> None:
        self.tabbed_content.active = "tab-projects"
        if self.project_tree:
            self.set_focus(self.project_tree)

    def action_next_tab(self) -> None:
        tabbed = self._get_tabbed()
        panes = [p for p in tabbed.query(TabPane)]
        ids   = [p.id for p in panes if p.id]
        if not ids:
            return
        try:
            idx = ids.index(tabbed.active)
        except ValueError:
            idx = 0
        tabbed.active = ids[(idx + 1) % len(ids)]

    def _get_search_input(self) -> Optional[Input]:
        """Return the search Input widget from the uncategorized list."""
        uncat = getattr(self, "uncategorized_list", None)
        if uncat is None:
            return None
        try:
            widget = uncat.query_one("#uncategorized-search")
        except Exception:
            return None
        return widget if isinstance(widget, Input) else None
    
    async def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "tab-uncategorized":
            # Ensure search is hidden when switching to this tab
            if self.uncategorized_list:
                self.uncategorized_list.search_active = False
                # Focus first container card
                first_card = None
                for child in self.uncategorized_list.children:
                    if isinstance(child, ContainerCard):
                        first_card = child
                        break
                if first_card:
                    self.set_focus(first_card)
                    self.uncategorized_list.selected_index = 0

    def is_projects_tab_active(self) -> bool:
        """Check if the Projects tab is currently active"""
        tabbed_content = self.query_one(TabbedContent)
        return tabbed_content.active == "tab-projects"

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
                for item in containers:
                    # be flexible about tuple length (works if containers are 5-tuple or 7-tuple)
                    try:
                        _, cid, name, image, status, *rest = item
                    except ValueError:
                        # something unexpected; skip this container safely
                        continue
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

    async def refresh_container_list(self, containers: list[tuple[int, str, str, str, str, str, str]]):
        await self.sync_card_list(containers, self.cards, self.container_list)

    

    # In the sync_card_list method, update the parameter type and unpacking
    async def sync_card_list(
        self,
        container_data: list[tuple[int, str, str, str, str, str, str]],  # Changed to list
        container_map: dict[str, ContainerCard],
        mount_target: Vertical
    ):
        current_focused = self.screen.focused
        focused_id = getattr(current_focused, 'container_id', None) if (current_focused and isinstance(current_focused, ContainerCard)) else None
        
        new_ids = {cid for _, cid, *_ in container_data}
        old_ids = set(container_map.keys())

        # Remove cards that no longer exist
        for cid in old_ids - new_ids:
            card = container_map.pop(cid)
            await card.remove()

        # Create a mapping of container ID to status for quick lookup
        status_map = {cid: status for _, cid, _, _, status, _, _ in container_data}  # Added unpacking for ports and created

        for cid in old_ids & new_ids:
            if cid in container_map and cid in status_map:
                container_map[cid].update_status(status_map[cid])
        
        # Add new cards - note the additional parameters
        for idx, cid, name, image, status, ports, created in container_data:  # Now unpacking all 7 values
            if cid not in container_map:
                card = ContainerCard(idx, cid, name, image, status, ports, created)
                container_map[cid] = card
                await mount_target.mount(card)

        # Restore focus if the focused container still exists
        if focused_id:
            focused_card = self.get_container_card_by_id(focused_id)
            if focused_card:
                self.set_focus(focused_card)
        else:
            # Find first ContainerCard child (skip the search Input if present)
            first_card = None
            for child in mount_target.children:
                if isinstance(child, ContainerCard):
                    first_card = child
                    break

            if first_card:
                self.set_focus(first_card)

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

        self.current_project = self.get_selected_project()

    async def on_container_action_screen_selected(self, message: ContainerActionScreen.Selected):
        cid = message.container_id
        action = message.action
        self.disabled = False
        
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
            
            if isinstance(label, Text):
                raw_label = label.plain.strip()
            else:
                raw_label = str(label).strip()
            
            if raw_label and len(raw_label) > 1:
                return raw_label[1:].strip()
            return raw_label
        return None

    def notify_success(self, message: str) -> None:
        """Show a success notification."""
        self.notify(message, severity="information", timeout=3)

    def notify_error(self, message: str) -> None:
        """Show an error notification."""
        self.notify(message, severity="error", timeout=5)

    def notify_warning(self, message: str) -> None:
        """Show a warning notification."""
        self.notify(message, severity="warning", timeout=4)