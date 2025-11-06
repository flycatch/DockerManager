
from textual import events
from textual_terminal import Terminal
from textual.app import ComposeResult
from textual.widgets import Static
import shutil

# --- Monkey patch textual-terminal key handling ---

async def patched_on_key(self, event: events.Key) -> None:
    if self.emulator is None:
        return

    if event.key == "shift+escape":
        self.app.set_focus(None)
        return

    event.stop()

    control_key_map = {
        "ctrl+c": "\x03",
        "ctrl+d": "\x04",
        "ctrl+z": "\x1A",
        "ctrl+r": "\x12",
        "ctrl+a": "\x01",
        "ctrl+e": "\x05",
        "ctrl+k": "\x0B",
        "ctrl+u": "\x15",
        "ctrl+l": "\x0C",
    }

    if event.key in control_key_map:
        await self.send_queue.put(["stdin", control_key_map[event.key]])
    elif event.key == "enter":
        await self.send_queue.put(["stdin", "\n"])
    elif event.key == "backspace":
        await self.send_queue.put(["stdin", "\x7f"])
    else:
        char = self.ctrl_keys.get(event.key) or event.character
        if char:
            await self.send_queue.put(["stdin", char])

Terminal.on_key = patched_on_key


# --- Container shell widget using textual-terminal ---

class ContainerShell(Static):
    """Widget that runs an interactive shell inside a Docker container."""

    def __init__(self, container_id: str, **kwargs):
        super().__init__(**kwargs)
        self.container_id = container_id
        self.terminal = None

    def compose(self) -> ComposeResult:
        """Create a terminal running docker exec."""
        shell = "/bin/bash" if shutil.which("bash") else "/bin/sh"
        docker_cmd = f"docker exec -i -t {self.container_id} {shell}"

        self.terminal = Terminal(
            command=docker_cmd,
            id="container-terminal"
        )
        yield self.terminal

    def on_mount(self) -> None:
        """Start the terminal when mounted. Focus is handled by the parent screen
        when the Terminal tab becomes active so the terminal doesn't steal focus
        on initial mount."""
        if self.terminal:
            self.terminal.start()
