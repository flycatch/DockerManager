from textual.containers import Horizontal
from textual.widgets import Static
from textual.app import ComposeResult

class ContainerHeader(Horizontal):
    """Single-row header for the container table."""

    def compose(self) -> ComposeResult:
        yield Static("Container Name", classes="col name header")
        yield Static("Image", classes="col image header")
        yield Static("Status", classes="col status header")
