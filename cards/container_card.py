from textual.widgets import Static
from textual.app import ComposeResult

class ContainerCard(Static):
    def __init__(self, idx: int, container_id: str, name: str, image: str, status: str):
        super().__init__(classes="container-card")
        self.idx = idx
        self.container_id = container_id
        self.container_name = name
        self.image = image
        self.status = status
        self.status_widget: Static | None = None

    can_focus = True

    def compose(self) -> ComposeResult:
        # Removed idx from display
        yield Static(f"[b]{self.container_name}[/b]", classes="col name")
        yield Static(self.image, classes="col image")
        self.status_widget = Static(self.status, classes="col status")
        yield self.status_widget

    def update_status(self, new_status: str):
        if self.status == new_status:
            return
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
