# Fixed ContainerCard class
from textual.widgets import Static
from textual.app import ComposeResult

class ContainerCard(Static):
    def __init__(self, idx: int, container_id: str, name: str, image: str, status: str, ports: str, created: str):
        super().__init__(classes="container-card")
        self.idx = idx
        self.container_id = container_id
        self.container_name = name
        self.image = image
        self.status = status
        self.ports = ports
        self.created = created
        self.status_widget: Static | None = None

    @property
    def status_key(self) -> str:
        """Normalize Docker status string into one of: running, exited, restarting, paused, dead."""
        s = (self.status or "").lower()
        if s.startswith("up"):
            return "running"
        elif s.startswith("exited"):
            return "exited"
        elif s.startswith("restarting"):
            return "restarting"
        elif s.startswith("paused"):
            return "paused"
        elif s.startswith("dead"):
            return "dead"
        return "other"

    can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(self.container_id, classes="col id")
        yield Static(f"[b]{self.container_name}[/b]", classes="col name")
        yield Static(self.image, classes="col image")
        yield Static(self.created, classes="col created")
        yield Static(self.ports, classes="col ports")
        self.status_widget = Static(self.status, classes="col status")
        yield self.status_widget
        # Apply initial status class
        self.update_status(self.status)  # This will set the class without redundant update if status matches

    def update_status(self, new_status: str):
        if self.status == new_status:
            # Still apply classes for initial setup
            pass
        self.status = new_status
        if self.status_widget:
            self.status_widget.remove_class("status-running")
            self.status_widget.remove_class("status-stopped")
            self.status_widget.remove_class("status-exited")
            if "running" in new_status.lower():
                self.status_widget.add_class("status-running")
            elif "stopped" in new_status.lower() or "exited" in new_status.lower():
                self.status_widget.add_class("status-stopped")
            elif "paused" in new_status.lower():
                self.status_widget.add_class("status-exited")
            self.status_widget.update(new_status)
            self.status_widget.refresh()
            self.refresh()