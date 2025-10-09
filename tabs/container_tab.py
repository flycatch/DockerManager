from textual.binding import Binding
from typing import Optional
from textual.app import ComposeResult
from textual.widgets import  Input, Static
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Select
from cards.container_card import ContainerCard
from container_action_menu import ContainerActionScreen
from cards.container_header import ContainerHeader
import asyncio
from widget.loading_screen import LoadingOverlay

class ContainersTab(Vertical, can_focus=True):
    """A container view for Docker containers with filtering and search.
    
    This widget provides a scrollable, filterable list of Docker containers with:
    - Search functionality for container name/image/status
    - Filter dropdown for container status
    - Keyboard navigation
    - Container action menu integration
    - Responsive status updates
    
    Key Bindings:
    - down/up: Navigate containers
    - enter: Open container actions menu
    - /: Focus search
    - f: Toggle filter dropdown
    - escape: Clear search/filter
    """
    BINDINGS = [
        Binding("down", "focus_next", "Next", show=True),
        Binding("up", "focus_previous", "Previous", show=True),
        Binding("enter", "open_menu", "Actions", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("f", "toggle_filter", "Filter", show=True),   # NEW
        Binding("escape", "clear_search_or_filter", "Clear", show=False),  # UPDATED
    ]

    def __init__(self, *, id: str | None = None):
        """Initialize the containers tab.
        
        Args:
            id: Optional widget ID for styling/querying
            
        The tab maintains state for:
        - Current selection index
        - Search activation status
        - Filter activation status
        - Input field references
        - No-results message handling
        
        Uses Textual's reactive system for UI state management.
        """
        super().__init__(id=id)
        self.selected_index: int = 0
        self.search_active = reactive(False)
        self.filter_active = reactive(False)
        self.search_input: Optional[Input] = None
        self.filter_dropdown: Optional[Select] = None
        self.no_results_message: Optional[Static] = None


    def compose(self) -> ComposeResult:
        """Compose the tab's widget hierarchy.
        
        Returns:
            ComposeResult: The composed widget tree
        
        Creates a layout with:
        1. Search input field (initially hidden)
        2. Container list header
        3. Filter dropdown (initially hidden)
        4. Container cards section
        
        The layout is designed to be responsive and maintain proper
        focus order for keyboard navigation.
        """
        # search input
        self.search_input = Input(
            placeholder="Search containers (name, image, status)...",
            id="uncategorized-search",
            classes="search-input hidden"
        )
        yield self.search_input
        yield ContainerHeader()  # Add the header here, below the search input

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
        if not self.filter_dropdown:
            return

        if not self.filter_active:
            # Open filter
            self.filter_active = True
            self.filter_dropdown.styles.display = "block"
            self.app.set_focus(self.filter_dropdown)
        else:
            # Close filter
            self.filter_active = False
            self.filter_dropdown.styles.display = "none"
            self.app.set_focus(self._get_selected_card() or self)

        self.filter_dropdown.refresh()



    def action_clear_search_or_filter(self) -> None:
        """Escape key closes search or filter menu if active."""
        if self.search_active:
            self.action_clear_search()
            return

        if self.filter_dropdown and self.filter_dropdown.styles.display != "none":
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