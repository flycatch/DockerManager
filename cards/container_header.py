from textual.widgets import Static
from textual.app import ComposeResult

"""Container list header widget module.

This module provides a header widget for Docker container lists,
ensuring consistent column alignment and styling across the application.
"""

class ContainerHeader(Static):
    """A header widget displaying column titles for container lists.
    
    The header provides consistent column titles and styling for:
    - Container ID
    - Container name
    - Image name
    - Creation time
    - Port mappings
    - Container status
    
    The header uses CSS grid classes to align with ContainerCard widgets,
    ensuring proper column alignment throughout the container list.
    """

    def __init__(self):
        super().__init__(classes="container-header")

    def compose(self) -> ComposeResult:
        """Create the header's column layout.
        
        Returns:
            ComposeResult: The composed column headers
            
        Creates a grid layout with columns for:
        1. Container ID (monospace)
        2. Container name (bold)
        3. Image name
        4. Creation time
        5. Port mappings
        6. Status (with color coding)
        
        Each column uses consistent CSS classes for proper alignment
        with the container cards below.
        """
        yield Static("ID", classes="col id")
        yield Static("Name", classes="col name")
        yield Static("Image", classes="col image")
        yield Static("Created", classes="col created")
        yield Static("Ports", classes="col ports")
        yield Static("Status", classes="col status")
