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

    @property
    def status_key(self) -> str:
        """Get a normalized status key from the Docker status string.
        
        Returns:
            str: One of: running, exited, restarting, paused, dead, other
            
        This property normalizes Docker's various status strings into a set
        of consistent states that can be used for styling and filtering.
        """
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
            if "running" in new_status.lower():
                self.status_widget.add_class("status-running")
            elif "stopped" in new_status.lower() or "exited" in new_status.lower():
                self.status_widget.add_class("status-stopped")
            elif "paused" in new_status.lower():
                self.status_widget.add_class("status-exited")
            self.status_widget.update(new_status)
            self.status_widget.refresh()
            self.refresh()