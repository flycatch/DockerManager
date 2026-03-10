# Fixed ContainerCard class
"""Docker container card UI widget module.

This module provides a visual widget for displaying Docker container information
in a card format. Each card shows key container attributes like ID, name,
status, and ports in a consistent and visually appealing layout.
"""

from textual.widgets import Static
from textual.app import ComposeResult

class ContainerCard(Static):
    """A widget displaying Docker container information in a card format.
    
    This widget creates a focusable card that shows container details including:
    - Container ID
    - Container name
    - Image name
    - Creation time
    - Port mappings
    - Container status
    
    The card uses color-coding and styling to indicate different container
    states and provides a consistent interface for container management.
    """
    
    def __init__(self, idx: int, container_id: str, name: str, image: str, status: str, ports: str, created: str):
        """Initialize a container card with container details.
        
        Args:
            idx: Index for sorting/ordering
            container_id: Docker container ID
            name: Container name
            image: Image name/tag
            status: Container status string
            ports: Port mappings string
            created: Creation timestamp
        """
        super().__init__(classes="container-card")
        self.idx = idx
        self.container_id = container_id
        self.container_name = name
        self.image = image
        self.status = status
        self.ports = ports
        self.created = created
        self.status_widget: Static | None = None
        self._id_widget: Static | None = None
        self._name_widget: Static | None = None
        self._image_widget: Static | None = None
        self._created_widget: Static | None = None
        self._ports_widget: Static | None = None

    @staticmethod
    def _normalize_status_key(status: str) -> str:
        value = (status or "").strip().lower()
        if value.startswith("up"):
            return "running"
        if value.startswith("exited"):
            return "exited"
        if value.startswith("restarting"):
            return "restarting"
        if value.startswith("paused"):
            return "paused"
        if value.startswith("dead"):
            return "dead"
        if "running" in value:
            return "running"
        if "stopped" in value:
            return "exited"
        return "other"

    @property
    def status_key(self) -> str:
        """Get a normalized status key from the Docker status string.
        
        Returns:
            str: One of: running, exited, restarting, paused, dead, other
            
        This property normalizes Docker's various status strings into a set
        of consistent states that can be used for styling and filtering.
        """
        return self._normalize_status_key(self.status)

    can_focus = True

    def compose(self) -> ComposeResult:
        """Create the card's visual layout.
        
        Returns:
            ComposeResult: The hierarchy of widgets making up the card
            
        Layout structure:
        - Container ID (monospace)
        - Container name (bold)
        - Image name
        - Creation time
        - Port mappings
        - Status indicator (color-coded)
        
        The layout uses CSS grid classes for consistent column alignment
        across multiple cards.
        """
        self._id_widget = Static(self.container_id[:12], classes="col id")
        yield self._id_widget
        self._name_widget = Static(f"[b]{self.container_name}[/b]", classes="col name")
        yield self._name_widget
        self._image_widget = Static(self.image, classes="col image")
        yield self._image_widget
        self._created_widget = Static(self.created, classes="col created")
        yield self._created_widget
        self._ports_widget = Static(self.ports, classes="col ports")
        yield self._ports_widget
        self.status_widget = Static(self.status, classes="col status")
        yield self.status_widget
        # Apply initial status class
        self.update_status(self.status)  # This will set the class without redundant update if status matches

    def update_status(self, new_status: str):
        """Update the container's status and refresh the display.
        
        Args:
            new_status: The new status string from Docker
            
        This method:
        1. Updates the internal status
        2. Refreshes the status display
        3. Updates status-based styling
        
        The method is optimized to avoid unnecessary updates when the
        status hasn't changed.
        """
        if self.status == new_status:
            # Still apply classes for initial setup
            pass
        self.status = new_status
        if self.status_widget:
            self.status_widget.remove_class("status-running")
            self.status_widget.remove_class("status-stopped")
            self.status_widget.remove_class("status-exited")
            status_key = self._normalize_status_key(new_status)
            if status_key == "running":
                self.status_widget.add_class("status-running")
            elif status_key == "exited":
                self.status_widget.add_class("status-stopped")
            elif status_key == "paused":
                self.status_widget.add_class("status-exited")
            self.status_widget.update(new_status)
            self.status_widget.refresh()
            self.refresh()

    def update_details(self, name: str, image: str, status: str, ports: str, created: str) -> None:
        self.container_name = name
        self.image = image
        self.ports = ports
        self.created = created
        if self._name_widget is not None:
            self._name_widget.update(f"[b]{self.container_name}[/b]")
        if self._image_widget is not None:
            self._image_widget.update(self.image)
        if self._created_widget is not None:
            self._created_widget.update(self.created)
        if self._ports_widget is not None:
            self._ports_widget.update(self.ports)
        self.update_status(status)
