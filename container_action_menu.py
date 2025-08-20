from textual.screen import Screen
from textual.widgets import Static, Input, Footer, TabbedContent, TabPane
from textual.message import Message
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.events import Key
import asyncio

from container_logs import stream_logs
from container_exec import open_docker_shell

import re

VT100_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_vt100(text: str) -> str:
    return VT100_ESCAPE_PATTERN.sub('', text)

class ContainerActionScreen(Screen):
    BINDINGS = [
        Binding("s", "do_action('start')", "Start"),
        Binding("p", "do_action('stop')", "Stop"),
        Binding("d", "do_action('delete')", "Delete"),
        Binding("l", "switch_tab('Logs')", "Logs Tab"),
        Binding("t", "switch_tab('Terminal')", "Shell Tab"),
        Binding("/", "focus_filter", "Filter Logs"),
        Binding("ctrl+l", "clear_shell", "Clear Shell"),
        Binding("escape", "handle_escape", "Close"),
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
        self.shell_lines: list[str] = []
        self.keep_streaming = False
        self.filter_text = ""
        self.shell_reader = None
        self.shell_writer = None
        self.command_history: list[str] = []
        self.history_index: int = -1

    def compose(self):
        with TabbedContent():
            with TabPane("Logs", id="Logs"):
                with VerticalScroll(id="log-scroll", classes="log-container"):
                    yield Static("", id="log-output", classes="log-text")
                yield Input(
                    placeholder="🔍 Filter logs...",
                    id="log-filter",
                    classes="menu-input hidden"
                )

            with TabPane("Terminal", id="Terminal"):
                with VerticalScroll(id="shell-scroll", classes="shell-container"):
                    yield Static("", id="shell-output", classes="shell-text")
                yield Input(
                    placeholder="💻 Type shell command...",
                    id="shell-input",
                    classes="menu-input"
                )

        yield Footer()

    def on_mount(self):
        self.set_focus(None)
        self.keep_streaming = True
        self.set_interval(0.5, self.update_logs, name="log_ui")
        self.run_worker(self.stream_logs, group="logs", thread=True)

    def on_key(self, event: Key) -> None:
        shell_input = self.query_one("#shell-input", Input)
        if shell_input.has_focus:
            if event.key == "up":
                if self.command_history and self.history_index > 0:
                    self.history_index -= 1
                    shell_input.value = self.command_history[self.history_index]
            elif event.key == "down":
                if self.command_history and self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    shell_input.value = self.command_history[self.history_index]
                else:
                    self.history_index = len(self.command_history)
                    shell_input.value = ""

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "log-filter":
            self.filter_text = event.value.strip().lower()
            event.input.add_class("hidden")
            self.set_focus(None)
            self.refresh_logs()

        elif event.input.id == "shell-input":
            command = event.value.strip()
            event.input.value = ""

            if command:
                self.command_history.append(command)
                self.history_index = len(self.command_history)

                # Handle `clear` manually
                if command == "clear":
                    self.shell_lines.clear()
                    self.query_one("#shell-output", Static).update("")
                else:
                    if self.shell_writer:
                        self.shell_writer.write((command + "\n").encode())
                        await self.shell_writer.drain()

            # Always refresh the view
            self.query_one("#shell-output", Static).update(
                "".join(self.shell_lines[-1000:])
            )
            self.query_one("#shell-scroll", VerticalScroll).scroll_end(animate=False)


    def action_handle_escape(self):
        filter_input = self.query_one("#log-filter", Input)
        if filter_input.has_focus:
            filter_input.add_class("hidden")
            self.set_focus(None)
        else:
            self.action_pop_screen()

    def action_focus_filter(self):
        self.query_one("#log-filter", Input).remove_class("hidden")
        self.set_focus(self.query_one("#log-filter", Input))

    def action_clear_shell(self):
        self.shell_lines.clear()
        self.query_one("#shell-output", Static).update("")

    def update_logs(self):
        self.refresh_logs()

    def refresh_logs(self):
        scroll_view = self.query_one("#log-scroll", VerticalScroll)
        log_output = self.query_one("#log-output", Static)

        # Check if user is already at bottom
        at_bottom = scroll_view.scroll_y + scroll_view.size.height >= scroll_view.virtual_size.height - 1

        filtered = [
            self.colorize_log(line)
            for line in self.log_lines[-200:]
            if not self.filter_text or self.filter_text in line.lower()
        ]
        log_output.update("\n".join(filtered))

        # Only auto-scroll if already at bottom
        if at_bottom:
            scroll_view.scroll_end(animate=False)


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

    async def action_open_shell(self):
        if self.shell_reader and self.shell_reader.at_eof():
            self.shell_reader = self.shell_writer = None

        if self.shell_reader is None:
            self.shell_lines.clear()
            self.query_one("#shell-output", Static).update("")
            self.shell_reader, self.shell_writer = await open_docker_shell(self.container_id)
            asyncio.create_task(self.read_shell_output())
            self.set_focus(self.query_one("#shell-input"))

    async def read_shell_output(self):
        print("[DEBUG] Starting shell output reader")
        try:
            while self.shell_reader:
                data = await self.shell_reader.read(1024)
                if not data:
                    print("[DEBUG] No more data, exiting shell reader")
                    self.shell_lines.append("[red][DISCONNECTED] Shell session ended.[/red]\n")
                    self.query_one("#shell-output", Static).update(
                        "".join(self.shell_lines[-1000:])
                    )
                    break

                decoded = data.decode(errors="ignore")
                clean_output = strip_vt100(decoded)

                self.shell_lines.append(clean_output)
                scroll_view = self.query_one("#shell-scroll", VerticalScroll)
                output_widget = self.query_one("#shell-output", Static)

                at_bottom = scroll_view.scroll_y + scroll_view.size.height >= scroll_view.virtual_size.height - 1

                output_widget.update("".join(self.shell_lines[-1000:]))

                if at_bottom:
                    scroll_view.scroll_end(animate=False)

        except Exception as e:
            self.shell_lines.append(f"[red][ERROR] Shell closed: {e}[/red]\n")
            print(f"[ERROR] Exception in shell reader: {e}")
            self.query_one("#shell-output", Static).update(
                "".join(self.shell_lines[-1000:])
            )




    async def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tab.id == "Terminal":
            await self.action_open_shell()
            self.set_focus(self.query_one("#shell-input"))

    def action_do_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self.app.pop_screen()

    def action_pop_screen(self) -> None:
        self.keep_streaming = False
        if self.shell_writer:
            self.shell_writer.close()
        self.app.pop_screen()

    def action_switch_tab(self, tab: str) -> None:
        try:
            self.query_one(TabbedContent).active = tab
            if tab == "Terminal":
                self.call_after_refresh(self.action_open_shell)  # Ensure shell starts
        except Exception:
            self.app.bell()


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
