import asyncio
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Input, Static

from cards.image_card import ImageCard
from image_action_menu import ImageActionScreen
from widgets.loading_screen import LoadingOverlay


class ImagesTab(Vertical, can_focus=True):
    search_active = reactive(False)

    BINDINGS = [
        Binding("down", "focus_next", "Next", show=True),
        Binding("up", "focus_previous", "Previous", show=True),
        Binding("enter", "open_image", "Open", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("escape", "clear_search", "Clear", show=False),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.selected_index = 0
        self.search_input: Optional[Input] = None
        self.no_results_message: Optional[Static] = None

    def compose(self) -> ComposeResult:
        self.search_input = Input(
            placeholder="Search images by tag, digest, or id...",
            id="images-search",
            classes="search-input hidden",
        )
        yield self.search_input
        yield Static("REFERENCE        IMAGE ID       SIZE        CREATED           CONTAINERS", id="image-list-header")
        no_results = Static("No images match the current search", id="images-no-results", classes="hidden")
        no_results.styles.display = "none"
        self.no_results_message = no_results
        yield no_results

    def watch_search_active(self, active: bool) -> None:
        if self.search_input is None:
            return
        self.search_input.styles.display = "block" if active else "none"
        if not active:
            for card in self.query(ImageCard):
                card.styles.display = "block"

    def action_focus_search(self) -> None:
        if self.search_input is None:
            return
        self.search_active = True
        self.search_input.value = ""
        self.search_input.styles.display = "block"
        self.app.set_focus(self.search_input)

    def action_clear_search(self) -> None:
        if self.search_input is None:
            return
        self.search_active = False
        self.search_input.value = ""
        self.search_input.styles.display = "none"
        for card in self.query(ImageCard):
            card.styles.display = "block"
        cards = self._visible_cards()
        if cards:
            self.selected_index = 0
            self.app.set_focus(cards[0])

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "images-search":
            return
        query = (event.value or "").strip().lower()
        visible_count = 0
        for card in self.query(ImageCard):
            haystack = f"{card.reference} {card.image_id}".lower()
            is_match = not query or query in haystack
            card.styles.display = "block" if is_match else "none"
            if is_match:
                visible_count += 1
        if self.no_results_message is not None:
            self.no_results_message.styles.display = "none" if visible_count else "block"
        visible_cards = self._visible_cards()
        if visible_cards and self.app.screen.focused != self.search_input:
            self.selected_index = min(self.selected_index, len(visible_cards) - 1)
            self.app.set_focus(visible_cards[self.selected_index])

    def _visible_cards(self) -> list[ImageCard]:
        return [card for card in self.query(ImageCard) if card.styles.display != "none"]

    def _selected_card(self) -> ImageCard | None:
        visible = self._visible_cards()
        if not visible:
            return None
        return visible[self.selected_index % len(visible)]

    def action_focus_next(self) -> None:
        visible = self._visible_cards()
        if not visible:
            return
        self.selected_index = (self.selected_index + 1) % len(visible)
        self.app.set_focus(visible[self.selected_index])

    def action_focus_previous(self) -> None:
        visible = self._visible_cards()
        if not visible:
            return
        self.selected_index = (self.selected_index - 1) % len(visible)
        self.app.set_focus(visible[self.selected_index])

    def action_open_image(self) -> None:
        card = self._selected_card()
        if card is None:
            return
        overlay = LoadingOverlay(f"Opening image {card.reference}...")
        self.app.screen.mount(overlay)

        async def _open_screen() -> None:
            await asyncio.sleep(0.1)
            self.app.push_screen(ImageActionScreen(card.image_id, card.reference))
            await overlay.remove_self()

        self.app.run_worker(_open_screen())
