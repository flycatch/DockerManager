from textual.screen import Screen
from textual.widgets import Static
from textual.message import Message
from textual.binding import Binding
from textual.containers import Vertical


class ContainerActionScreen(Screen):
    BINDINGS = [
        Binding("s", "do_action('start')", "Start"),
        Binding("p", "do_action('stop')", "Stop"),
        Binding("l", "do_action('logs')", "Logs"),
        Binding("e", "do_action('exec')", "Shell"),
        Binding("escape", "pop_screen", "Close"),
    ]

    class Selected(Message):
        def __init__(self, action: str, container_id: str):
            self.action = action
            self.container_id = container_id
            super().__init__()

    def __init__(self, container_id: str):
        super().__init__()
        self.container_id = container_id

    def compose(self):
        with Vertical(classes="modal-card"):
            yield Static(
                f"[b]Actions for: {self.container_id}[/b]", classes="menu-title"
            )
            yield Static(
                "[b]s[/b] Start   [b]p[/b] Stop   [b]l[/b] Logs   [b]e[/b] Shell   [b]Esc[/b] Close",
                classes="menu-keys",
            )

    def action_do_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self.app.pop_screen()

    def action_pop_screen(self) -> None:
        self.app.pop_screen()
