# loading_screen.py
from textual.containers import Container
from textual.widgets import LoadingIndicator, Static
from textual.app import ComposeResult
from textual.css.query import NoMatches

class LoadingOverlay(Container):
    can_focus = False
    can_scroll = False
    """A full-screen overlay with a centered spinner and message."""

    def __init__(self, message: str = "Loading...", **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        yield LoadingIndicator()
        yield Static(self.message, id="loading-message", classes="loading-message")

    def update_message(self, message: str) -> None:
        self.message = message
        try:
            self.query_one("#loading-message", Static).update(message)
        except NoMatches:
            pass

    async def remove_self(self) -> None:
        """Safely remove overlay if mounted."""
        try:
            await self.remove()
        except NoMatches:
            pass
