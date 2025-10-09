from textual.binding import Binding
from typing import Any, Optional
from textual.app import ComposeResult
from textual.widgets import Tree,Input, Static
from textual.containers import Horizontal
from rich.text import Text
from textual.reactive import reactive
from cards.container_card import ContainerCard
from container_action_menu import ContainerActionScreen
from service import (
    start_project, stop_project, delete_project, restart_project
)
import asyncio
from widget.loading_screen import LoadingOverlay


class ProjectsTab(Horizontal, can_focus=True):
    """A tab for managing Docker Compose projects and their containers.
    
    This widget provides a comprehensive interface for Docker Compose projects:
    - Project list with container details
    - Project-wide operations (start/stop/restart/delete)
    - Search functionality
    - Keyboard navigation
    - Project state management
    
    Key Bindings:
    - down/up: Navigate projects
    - enter: Open project actions menu
    - u: Start project
    - o: Stop project
    - r: Restart project
    - x: Delete project
    - /: Focus search
    - escape: Clear search
    """
    BINDINGS = [
        Binding("down", "focus_next", "Next", show=True),
        Binding("up", "focus_previous", "Previous", show=True),
        Binding("enter", "open_menu", "Actions", show=True),
        Binding("u", "start_project", "Up/Start", show=True),
        Binding("o", "stop_project", "Down/Stop", show=True),
        Binding("r", "restart_project", "Restart", show=True),
        Binding("x", "delete_project", "Delete", show=True),
        Binding("/", "focus_search", "Search", show=True),         # open search
        Binding("escape", "clear_search", "Clear", show=False),    # clear/close search
    ]
    
    def __init__(self, *, id: str | None = None):
        """Initialize the projects tab.
        
        Args:
            id: Optional widget ID for styling/querying
            
        The tab maintains state for:
        - Current project selection index
        - Search activation status
        - Input field references
        - No-results message handling
        
        Uses Textual's reactive system for UI state management
        to handle search visibility and project filtering.
        """
        super().__init__(id=id)
        self.selected_index: int = 0
        self.search_active = reactive(False)
        self.search_input: Optional[Input] = None
        self.no_results_message: Optional[Static] = None

    def compose(self) -> ComposeResult:
        """Compose the tab's widget hierarchy.
        
        Returns:
            ComposeResult: The composed widget tree
            
        Creates a layout with:
        1. Search input field (initially hidden)
        2. Project tree
        3. No-results message (initially hidden)
        
        Layout Notes:
        - Search input appears above tree due to mount order
        - Hidden elements managed by reactive properties
        - Maintains focus order for keyboard navigation
        """
        # Search input (hidden by default). Because DockerManager mounts the Tree
        # as a child of this ProjectsTab, the Input will appear above the Tree.
        self.search_input = Input(
            placeholder="Search projects... (press Enter to jump/focus)",
            id="project-search",
            classes="search-input hidden"
        )
        # hide by default; watch_search_active will show/hide
        self.search_input.styles.display = "none"
        yield self.search_input

        # No-results message (hidden by default)
        no_results_msg = Static(
            "No projects match your search",
            id="project-no-results",
            classes="hidden"
        )
        no_results_msg.styles.display = "none"
        self.no_results_message = no_results_msg
        yield no_results_msg

        # Note: your DockerManager.compose still mounts the Tree and container_list
        # inside this ProjectsTab, so they will appear after the search input.

    # ---------- Search actions ----------
    def action_focus_search(self) -> None:
        """Show project search input and focus it."""
        if not self.search_input:
            return
        self.search_active = True
        self.search_input.value = ""
        self.search_input.styles.display = "block"
        self.app.set_focus(self.search_input)

    def action_clear_search(self) -> None:
        """Hide & clear the project search input; reset selection/focus to tree."""
        if not self.search_input:
            return
        self.search_input.value = ""
        self.search_active = False
        self.search_input.styles.display = "none"
        # hide no-results message
        if self.no_results_message:
            self.no_results_message.styles.display = "none"
            self.no_results_message.refresh()
        # Return focus to the Tree if present, otherwise to this tab
        try:
            tree = self.query_one(Tree)
            self.app.set_focus(tree)
        except Exception:
            self.app.set_focus(self)

    def watch_search_active(self, active: bool) -> None:
        """Update visibility CSS when toggling the search input."""
        if not self.search_input:
            return
        if active:
            self.search_input.add_class("search-active")
            self.search_input.styles.display = "block"
        else:
            self.search_input.remove_class("search-active")
            self.search_input.styles.display = "none"

    async def on_input_changed(self, event: Input.Changed) -> None:
        """
        When the project search input changes, jump/select the first matching tree node.
        IMPORTANT: do NOT move focus away from the Input here — that caused the single-letter typing bug.
        """
        if event.input.id != "project-search" or not self.search_active:
            return

        query = (event.value or "").strip().lower()
        try:
            tree = self.query_one(Tree)
        except Exception:
            return

        matches: list[Any] = []
        for node in tree.root.children:
            label = node.label.plain if isinstance(node.label, Text) else str(node.label)
            label_text = label.strip().lower()
            # strip leading glyph like "🔹 " if present
            if label_text and len(label_text) > 1:
                compare_text = label_text[1:].strip()
            else:
                compare_text = label_text

            if not query or query in compare_text:
                matches.append(node)

        # show/hide no-results message
        if self.no_results_message:
            if not matches:
                self.no_results_message.styles.display = "block"
            else:
                self.no_results_message.styles.display = "none"
            self.no_results_message.refresh()

        # Select the first match so your DockerManager.on_tree_node_selected still runs,
        # but DO NOT change focus — keep typing in the input.
        if matches:
            tree.select_node(matches[0])
        else:
            # If no matches, don't select anything
            try:
                tree.select_node(None)
            except Exception:
                pass

        # Keep focus in the input so user can type multiple characters uninterrupted.

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """
        When the user presses Enter inside the search Input:
        - if there's a match, focus the tree so they can navigate the project with keyboard.
        - otherwise keep focus in the input (or you could move focus to container list).
        """
        if event.input.id != "project-search":
            return

        try:
            tree = self.query_one(Tree)
        except Exception:
            return

        # If there's a selected node (i.e. a match), move focus to the tree.
        if tree.cursor_node:
            self.app.set_focus(tree)
        else:
            # No selected node — keep focus in input so user can keep typing
            self.app.set_focus(self.search_input)

    # ---------- existing actions (unchanged) ----------
    def _get_selected_card(self) -> ContainerCard | None:
        """Return currently selected container card, if any."""
        cards = [c for c in self.query(ContainerCard)]
        if not cards:
            return None
        return cards[self.selected_index % len(cards)]

    
    def action_open_menu(self) -> None:
        if card := self._get_selected_card():
            overlay = LoadingOverlay(f"Opening {card.container_name}...")
            self.app.screen.mount(overlay)  # ✅ mount to screen, not self
            overlay.refresh(layout=True)
            self.app.refresh()

            async def _open_screen():
                await asyncio.sleep(0.2)
                self.app.push_screen(
                    ContainerActionScreen(card.container_id, card.container_name)
                )
                await overlay.remove_self()

            self.app.run_worker(_open_screen())


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
