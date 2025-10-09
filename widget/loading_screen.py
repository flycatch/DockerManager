# loading_screen.py
from textual.containers import Container
from textual.widgets import LoadingIndicator, Static
from textual.app import ComposeResult
from textual.css.query import NoMatches

class LoadingOverlay(Container):
    """A full-screen overlay with a centered spinner and message."""

    DEFAULT_CSS = """
    LoadingOverlay {
        layer: overlay;
        background: rgba(0,0,0,0.6);
        align: center middle;
        height: 100%;
        width: 100%;
    }

    .loading-message {
        color: white;
        margin-top: 1;
        text-style: bold;
    }
    """

    def __init__(self, message: str = "Loading...", **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        yield LoadingIndicator()
        yield Static(self.message, classes="loading-message")

    async def remove_self(self) -> None:
        """Safely remove overlay if mounted."""
        try:
            await self.remove()
        except NoMatches:
            pass
