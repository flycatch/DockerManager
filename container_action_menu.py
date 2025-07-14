from textual.screen import Screen
from textual.widgets import Static, Input
from textual.message import Message
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from container_logs import stream_logs


class ContainerActionScreen(Screen):
    BINDINGS = [
        Binding("s", "do_action('start')", "Start"),
        Binding("p", "do_action('stop')", "Stop"),
        Binding("l", "show_logs", "Logs"),
        Binding("e", "do_action('exec')", "Shell"),
        Binding("/", "focus_filter", "Filter Logs"),
        Binding("escape", "handle_escape", "Close or Exit Filter"),
    ]

    class Selected(Message):
        def __init__(self, action: str, container_id: str):
            self.action = action
            self.container_id = container_id
            super().__init__()

    def __init__(self, container_id: str, container_name: str):
        super().__init__()
        self.container_id = container_id
        self.container_name = container_name
        self.log_lines: list[str] = []
        self.keep_streaming = False
        self.filter_text = ""
        self.logs_visible = False

    def compose(self):
        with Vertical(classes="modal-card"):
            yield Static(
                f"[b]Actions for: {self.container_id} {self.container_name}[/b]",
                classes="menu-title text-accent",
            )
            yield Static(
                "[b]s[/b] Start   [b]p[/b] Stop   [b]l[/b] Logs   [b]e[/b] Shell   [b]/[/b] Filter   [b]Esc[/b] Close",
                classes="menu-keys text-subtle",
            )
            with VerticalScroll(id="log-scroll", classes="hidden log-container"):
                yield Static("", id="log-output", classes="log-text")

            yield Input(
                placeholder="🔍 Filter logs...", id="log-filter", classes="hidden"
            )

    def on_mount(self):
        self.set_focus(None)

    def action_focus_filter(self):
        input_box = self.query_one("#log-filter", Input)
        input_box.remove_class("hidden")
        self.set_focus(input_box)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.filter_text = event.value.strip().lower()
        event.input.add_class("hidden")
        self.set_focus(None)
        self.refresh_logs()

    def action_handle_escape(self):
        input_box = self.query_one("#log-filter", Input)
        if input_box.has_focus:
            input_box.add_class("hidden")
            self.set_focus(None)
        else:
            self.action_pop_screen()

    def action_show_logs(self):
        log_scroll = self.query_one("#log-scroll", VerticalScroll)

        if self.logs_visible:
            log_scroll.add_class("hidden")
            self.logs_visible = False
            self.keep_streaming = False
        else:
            log_scroll.remove_class("hidden")
            self.logs_visible = True
            self.keep_streaming = True
            self.set_interval(0.5, self.update_logs, name="log_ui")
            self.run_worker(self.stream_logs, group="logs", thread=True)

    def update_logs(self):
        self.refresh_logs()

    def refresh_logs(self):
        log_output = self.query_one("#log-output", Static)
        filtered = []
        for line in self.log_lines[-200:]:
            if self.filter_text and self.filter_text not in line.lower():
                continue
            filtered.append(self.colorize_log(line))
        log_output.update("\n".join(filtered))
        scroll = self.query_one("#log-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def stream_logs(self):
        for line in stream_logs(
            self.container_id, follow=True, tail="100", timestamps=True
        ):
            if not self.keep_streaming:
                break
            line = line.decode(errors="ignore") if isinstance(line, bytes) else line
            self.log_lines.append(line)
            if len(self.log_lines) > 1000:
                self.log_lines.pop(0)

    def action_do_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self.app.pop_screen()

    def action_pop_screen(self) -> None:
        self.keep_streaming = False
        self.app.pop_screen()

    def colorize_log(self, line: str) -> str:
        upper = line.upper()
        if "ERROR" in upper:
            return f"[red]{line}[/red]"
        elif "WARN" in upper:
            return f"[yellow]{line}[/yellow]"
        elif "INFO" in upper:
            return f"[green]{line}[/green]"
        elif "DEBUG" in upper:
            return f"[blue]{line}[/blue]"
        return line
