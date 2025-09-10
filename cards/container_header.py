from textual.widgets import Static
from textual.app import ComposeResult

class ContainerHeader(Static):
    """Header row for container lists"""

    def __init__(self):
        super().__init__(classes="container-header")

    def compose(self) -> ComposeResult:
        yield Static("ID", classes="col id")
        yield Static("Name", classes="col name")
        yield Static("Image", classes="col image")
        yield Static("Created", classes="col created")
        yield Static("Ports", classes="col ports")
        yield Static("Status", classes="col status")
