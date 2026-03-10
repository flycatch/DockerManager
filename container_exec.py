from textual import events
from textual_terminal import Terminal
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static
from rich.align import Align
from rich.panel import Panel
from rich.text import Text
from service import get_container_state

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
        "ctrl+z": "\x1a",
        "ctrl+r": "\x12",
        "ctrl+a": "\x01",
        "ctrl+e": "\x05",
        "ctrl+k": "\x0b",
        "ctrl+u": "\x15",
        "ctrl+l": "\x0c",
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


class ContainerShell(Container):
    """Widget that runs an interactive shell inside a Docker container."""

    def __init__(self, container_id: str, **kwargs):
        super().__init__(**kwargs)
        self.container_id = container_id
        self.terminal = None
        self.status_message: Static | None = None

    def compose(self) -> ComposeResult:
        """Create a terminal running docker exec."""
        docker_cmd = (
            f"docker exec -i -t {self.container_id} "
            "sh -lc 'command -v bash >/dev/null 2>&1 && exec bash || exec sh'"
        )

        self.terminal = Terminal(command=docker_cmd, id="container-terminal")
        yield self.terminal
        self.status_message = Static("", id="container-terminal-status")
        yield self.status_message

    def on_mount(self) -> None:
        """Start the terminal when mounted. Focus is handled by the parent screen
        when the Terminal tab becomes active so the terminal doesn't steal focus
        on initial mount."""
        # Force shell area to fill available tab space so the PTY can resize.
        self.styles.width = "1fr"
        self.styles.height = "1fr"
        if self.terminal:
            self.terminal.styles.width = "1fr"
            self.terminal.styles.height = "1fr"
        if self.status_message:
            self.status_message.styles.width = "1fr"
            self.status_message.styles.height = "1fr"
        self.refresh_container_state()

    def refresh_container_state(self) -> bool:
        """Show the terminal only for running containers."""
        state = get_container_state(self.container_id) or "unknown"
        running = state in ("running", "restarting")
        if self.terminal:
            self.terminal.styles.display = "block" if running else "none"
        if self.status_message:
            self.status_message.styles.display = "none" if running else "block"
            if not running:
                self.status_message.update(
                    _build_status_notice(f"Container seems {state}")
                )
        if running and self.terminal:
            self.terminal.start()
        return running

    def ensure_started(self) -> bool:
        """Start (or restart) the terminal emulator if it is not running."""
        return self.refresh_container_state()


def _build_status_notice(message: str):
    text = Text(message, style="bold #f9e2af", justify="center")
    panel = Panel.fit(
        text,
        border_style="#f38ba8",
        title="Container State",
        title_align="center",
        padding=(1, 3),
    )
    return Align.center(panel, vertical="middle")
