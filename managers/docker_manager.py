from textual.binding import Binding
from typing import Dict, Any, Optional
from textual.app import ComposeResult, App
from textual.widgets import TabbedContent, TabPane, Tree, Footer, Input, Static
from textual.containers import Vertical, Horizontal
from textual.widgets import TabbedContent
from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Select
from cards.container_card import ContainerCard
from container_action_menu import ContainerActionScreen
from service import (
    get_projects_with_containers,
    start_container,
    stop_container,
    delete_container,
    start_project, stop_project, delete_project, restart_project
)

# -----------------------
# Custom tab containers
# -----------------------

class ContainersTab(Vertical, can_focus=True):
    """Container for All Containers tab with its own key bindings."""
    BINDINGS = [
        Binding("down", "focus_next", "Next", show=True),
        Binding("up", "focus_previous", "Previous", show=True),
        Binding("enter", "open_menu", "Actions", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("escape", "clear_search", "Clear Search", show=False),
        Binding("f", "toggle_filter", "Filter", show=True),   # NEW
        Binding("escape", "clear_search_or_filter", "Clear", show=False),  # UPDATED
    ]

    def __init__(self, *, id: str | None = None):
        super().__init__(id=id)
        self.selected_index: int = 0
        self.search_active = reactive(False)
        self.filter_active = reactive(False)
        self.search_input: Optional[Input] = None
        self.filter_dropdown: Optional[Select] = None
        self.no_results_message: Optional[Static] = None  # Add this line


    def compose(self) -> ComposeResult:
        # search input
        self.search_input = Input(
            placeholder="Search containers (name, image, status)...",
            id="uncategorized-search",
            classes="search-input hidden"
        )
        yield self.search_input

        # filter dropdown (hidden by default)
        self.filter_dropdown = Select(
            options=[
                ("All", "all"),
                ("Running", "running"),
                ("Restarting", "restarting"),
                ("Stopped", "exited"),
            ],
            prompt="Filter by status",
            compact=True,
            id="filter-dropdown",
            classes="hidden"
        )
        self.filter_dropdown.styles.display = "none"
        yield self.filter_dropdown
        
        # Create the no results message (hidden by default)
        no_results_msg = Static(
            "No containers match the current filter",
            id="no-results-message",
            classes="hidden"
        )
        no_results_msg.styles.display = "none"
        self.no_results_message = no_results_msg
        yield no_results_msg

    
    def action_toggle_filter(self) -> None:
        """Show or hide the filter dropdown."""
        if self.filter_dropdown:
            self.filter_active = not self.filter_active
            if self.filter_active:
                self.filter_dropdown.styles.display = "block"
                self.app.set_focus(self.filter_dropdown)
            else:
                self.filter_dropdown.styles.display = "none"
                self.app.set_focus(self._get_selected_card() or self)
            self.filter_dropdown.refresh()


    def action_clear_search_or_filter(self) -> None:
        """Escape key closes search or filter menu if active."""
        if self.search_active:
            self.action_clear_search()
            return

        if self.filter_active and self.filter_dropdown:
            self.filter_active = False
            self.filter_dropdown.styles.display = "none"
            self.filter_dropdown.refresh()
            self.app.set_focus(self._get_selected_card() or self)

    async def on_select_changed(self, event: Select.Changed) -> None:
        """Filter containers based on dropdown value and auto-close."""
        if event.select.id != "filter-dropdown":
            return
        selected = event.value or "all"
        cards = [c for c in self.query(ContainerCard)]

        for card in cards:
            if selected == "all":
                card.styles.display = "block"
            else:
                card.styles.display = "block" if card.status_key == selected else "none"

        # Show/hide no results message
        visible_cards = [c for c in cards if c.styles.display != "none"]
        if self.no_results_message:
            if not visible_cards:
                self.no_results_message.styles.display = "block"
            else:
                self.no_results_message.styles.display = "none"
            self.no_results_message.refresh()

        # Auto-close the filter dropdown after selection
        self.filter_active = False
        if self.filter_dropdown:
            self.filter_dropdown.styles.display = "none"
            self.filter_dropdown.refresh()

        # Reset focus to first visible card or to the tab itself if no cards
        if visible_cards:
            self.app.set_focus(visible_cards[0])
            self.selected_index = 0
        else:
            self.app.set_focus(self)



    def _get_search_input(self) -> Optional[Input]:
        """Find the search Input safely and ensure its type for the type-checker."""
        return self.search_input

    def _matches(self, card: ContainerCard, query: str) -> bool:
        """Return True if query matches name, image, or status."""
        name = getattr(card, "container_name", "") or ""
        image = getattr(card, "image", "") or getattr(card, "container_image", "") or ""
        status = getattr(card, "status", "") or ""
        hay = f"{name} {image} {status}".lower()
        return query in hay

    def action_focus_search(self) -> None:
        """Show search input and focus it."""
        inp = self._get_search_input()
        if inp:
            self.search_active = True
            inp.value = ""
            # Force the display immediately
            inp.styles.display = "block"
            self.app.set_focus(inp)

    def action_clear_search(self) -> None:
        """Clear search and hide the search input."""
        inp = self._get_search_input()
        if inp:
            inp.value = ""
            self.search_active = False
            # Hide the search input immediately
            inp.styles.display = "none"
            # Show all cards
            for card in self.query(ContainerCard):
                card.styles.display = "block"
            # Focus back to the first container card
            cards = [c for c in self.query(ContainerCard)]
            if cards:
                self.app.set_focus(cards[0])
                self.selected_index = 0

    def watch_search_active(self, active: bool) -> None:
        """Update CSS class and visibility when search becomes active/inactive"""
        inp = self._get_search_input()
        if inp:
            if active:
                inp.add_class("search-active")
                inp.styles.display = "block"
            else:
                inp.remove_class("search-active")
                inp.styles.display = "none"
                # Show all cards when search is deactivated
                for card in self.query(ContainerCard):
                    card.styles.display = "block"

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Filter visible ContainerCard widgets as the user types."""
        # Only process if this is the search input and search is active
        if event.input.id != "uncategorized-search" or not self.search_active:
            return
            
        query = (event.value or "").strip().lower()
        cards = [c for c in self.query(ContainerCard)]

        # Show/hide cards based on query
        for card in cards:
            if not query:
                card.styles.display = "block"
            else:
                card.styles.display = "block" if self._matches(card, query) else "none"

        # Show/hide no results message
        visible = [c for c in cards if c.styles.display != "none"]
        if self.no_results_message:
            if not visible:
                self.no_results_message.styles.display = "block"
            else:
                self.no_results_message.styles.display = "none"
            self.no_results_message.refresh()

        # If no visible cards, reset selected index
        if not visible:
            self.selected_index = 0
            return

        # If the search input is currently focused, keep it focused so typing continues
        search_widget = self._get_search_input()
        if search_widget is self.app.screen.focused:
            return

        # Otherwise, ensure there is a sensible focused ContainerCard
        if self.app.screen.focused not in visible:
            self.selected_index = 0
            if visible:
                self.app.set_focus(visible[0])

    def _get_selected_card(self) -> ContainerCard | None:
        """Return currently selected container card, if any."""
        cards = [c for c in self.query(ContainerCard) if c.styles.display != "none"]
        if not cards:
            return None
        return cards[self.selected_index % len(cards)]
    
    def _get_visible_cards(self) -> list[ContainerCard]:
        """Return list of currently visible container cards."""
        return [c for c in self.query(ContainerCard) if c.styles.display != "none"]
    
    # ---- Actions ----
    def action_focus_next(self) -> None:
        cards = self._get_visible_cards()
        if not cards:
            return
        self.selected_index = (self.selected_index + 1) % len(cards)
        self.app.set_focus(cards[self.selected_index])

    def action_focus_previous(self) -> None:
        cards = self._get_visible_cards()
        if not cards:
            return
        self.selected_index = (self.selected_index - 1) % len(cards)
        self.app.set_focus(cards[self.selected_index])

    def action_open_menu(self) -> None:
        if card := self._get_selected_card():
            self.app.push_screen(
                ContainerActionScreen(card.container_id, card.container_name)
            )


class ProjectsTab(Horizontal, can_focus=True):
    """Container for Compose Projects tab with its own key bindings."""
    BINDINGS = [
        Binding("down", "focus_next", "Next", show=True),
        Binding("up", "focus_previous", "Previous", show=True),
        Binding("enter", "open_menu", "Actions", show=True),
        Binding("u", "start_project", "Up/Start", show=True),
        Binding("o", "stop_project", "Down/Stop", show=True),
        Binding("r", "restart_project", "Restart", show=True),
        Binding("x", "delete_project", "Delete", show=True),
        Binding("escape", "switch_focus", "Switch Focus", show=False),
    ]
    
    def __init__(self, *, id: str | None = None):
        super().__init__(id=id)
        self.selected_index: int = 0

    def _get_selected_card(self) -> ContainerCard | None:
        """Return currently selected container card, if any."""
        cards = [c for c in self.query(ContainerCard)]
        if not cards:
            return None
        return cards[self.selected_index % len(cards)]

    def action_open_menu(self) -> None:
        if card := self._get_selected_card():
            self.app.push_screen(
                ContainerActionScreen(card.container_id, card.container_name)
            )

    def action_focus_next(self) -> None:
        cards = [c for c in self.query(ContainerCard)]
        if not cards:
            return
        self.selected_index = (self.selected_index + 1) % len(cards)
        self.app.set_focus(cards[self.selected_index])

    def action_focus_previous(self) -> None:
        cards = [c for c in self.query(ContainerCard)]
        if not cards:
            return
        self.selected_index = (self.selected_index - 1) % len(cards)
        self.app.set_focus(cards[self.selected_index])

    def _get_selected_project(self) -> str | None:
        tree = self.query_one(Tree)
        node = tree.cursor_node
        if node and node.data:
            label = node.label.plain if isinstance(node.label, Text) else str(node.label)
            if label and len(label) > 1:
                return label[1:].strip()
        return None

    def _maybe_run_refresh(self) -> None:
        """Call DockerManager.refresh_projects via getattr to avoid Pylance static error."""
        refresh = getattr(self.app, "refresh_projects", None)
        if callable(refresh):
            try:
                self.app.run_worker(refresh, exclusive=True, group="refresh")
            except Exception:
                pass

    def _notify(self, method: str, message: str) -> None:
        fn = getattr(self.app, method, None)
        if callable(fn):
            try:
                fn(message)
            except Exception:
                pass

    def action_start_project(self) -> None:
        if project := self._get_selected_project():
            if start_project(project):
                self._notify("notify_success", f"Started project: {project}")
                self._maybe_run_refresh()
            else:
                self._notify("notify_error", f"Failed to start project: {project}")

    def action_stop_project(self) -> None:
        if project := self._get_selected_project():
            if stop_project(project):
                self._notify("notify_success", f"Stopped project: {project}")
                self._maybe_run_refresh()
            else:
                self._notify("notify_error", f"Failed to stop project: {project}")

    def action_restart_project(self) -> None:
        if project := self._get_selected_project():
            if restart_project(project):
                self._notify("notify_success", f"Restarted project: {project}")
                self._maybe_run_refresh()
            else:
                self._notify("notify_error", f"Failed to restart project: {project}")

    def action_delete_project(self) -> None:
        if project := self._get_selected_project():
            if delete_project(project):
                self._notify("notify_success", f"Deleted project: {project}")
                self._maybe_run_refresh()
            else:
                self._notify("notify_error", f"Failed to delete project: {project}")

    def action_switch_focus(self) -> None:
        """Switch focus between the project tree and the container list."""
        current_focus = self.screen.focused
        tree = self.query_one(Tree)
        container_list = self.query_one("#container-list")
        if current_focus == tree:
            if container_list.children:
                self.app.set_focus(container_list.children[0])
        else:
            self.app.set_focus(tree)


class DockerManager(App):
    CSS_PATH = "../ui.tcss"
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
        self.projects: dict[str, list[tuple[int, str, str, str, str]]] = {}
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
                    self.container_list = Vertical(id="container-list")
                    yield self.project_tree
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