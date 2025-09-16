from textual.screen import ModalScreen
from textual.widgets import Static, Input, Footer, TabbedContent, TabPane
from textual.message import Message
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.events import Key
from typing import List, Optional, Any
import asyncio
import re
from container_logs import stream_logs
from container_exec import open_docker_shell, check_shell_availability


async def _safe_close(writer: Optional[asyncio.StreamWriter]) -> None:
    """Safely close a StreamWriter if it exists."""
    if writer:
        try:
            writer.close()
            if hasattr(writer, "wait_closed"):
                await writer.wait_closed()
        except Exception:
            pass
# --- helper constants and functions ---
TAB_WIDTH = 8
PROMPT = "$ "

def expand_tabs(text: str, tab_width: int = TAB_WIDTH) -> str:
    """Expand tabs to spaces with proper tab stops."""
    result = []
    for line in text.split('\n'):
        expanded_line = []
        col = 0
        for char in line:
            if char == '\t':
                spaces = tab_width - (col % tab_width)
                expanded_line.append(' ' * spaces)
                col += spaces
            else:
                expanded_line.append(char)
                col += 1
        result.append(''.join(expanded_line))
    return '\n'.join(result)


def _convert_ansi_to_textual(ansi_code: str) -> str:
    """Convert ANSI color codes to Textual markup."""
    if not ansi_code:
        return ""
    codes = ansi_code.split(';')
    textual_tags = []
    i = 0
    while i < len(codes):
        code = codes[i]
        if code == '0':
            # Reset all formatting
            return "[/]"
        elif code == '1':
            textual_tags.append("[bold]")
        elif code == '3':
            textual_tags.append("[dim]")
        elif code == '4':
            textual_tags.append("[underline]")
        elif code in ('30','31','32','33','34','35','36','37'):
            color_map = {
                '30':'black','31':'red','32':'green','33':'yellow',
                '34':'blue','35':'magenta','36':'cyan','37':'white'
            }
            textual_tags.append(f"[{color_map[code]}]")
        elif code in ('40','41','42','43','44','45','46','47'):
            color_map = {
                '40':'on black','41':'on red','42':'on green','43':'on yellow',
                '44':'on blue','45':'on magenta','46':'on cyan','47':'on white'
            }
            textual_tags.append(f"[{color_map[code]}]")
        i += 1
    return ''.join(textual_tags) if textual_tags else ""


def strip_vt100(text: str) -> str:
    """Remove VT100 escape sequences but preserve some formatting."""
    # First remove all non-color escape sequences
    text = re.sub(r'\x1B[^m]*[a-zA-Z]', '', text)  # Remove all non-color sequences
    text = re.sub(r'\x1B=', '', text)  # Remove specific sequences like \x1B=
    
    # Handle color sequences carefully
    text = re.sub(r'\x1B\[([0-9;]*)m',
                  lambda m: _convert_ansi_to_textual(m.group(1)),
                  text)
    
    # Clean up any remaining escape sequences
    text = re.sub(r'\x1B[^[]*\[[^m]*[a-ln-zA-Z]', '', text)
    return text

class ContainerActionScreen(ModalScreen):
    COMMON_BINDINGS: List[BindingType] = [
        Binding("left", "switch_tab('Logs')", "Logs Tab"),
        Binding("right", "switch_tab('Terminal')", "Shell Tab"),
        Binding("escape", "handle_escape", "Close", key_display="ESC"),
    ]
    
    LOGS_BINDINGS: List[BindingType] = COMMON_BINDINGS + [
        Binding("/", "focus_filter", "Filter Logs"),
        Binding("s", "do_action('start')", "Start"),
        Binding("p", "do_action('stop')", "Stop"),
        Binding("d", "do_action('delete')", "Delete"),
    ]
    
    TERMINAL_BINDINGS: List[BindingType] = COMMON_BINDINGS + [
        Binding("ctrl+l", "clear_shell", "Clear Shell"),
    ]

    # Start with logs bindings since Logs is the default tab
    BINDINGS: List[BindingType] = LOGS_BINDINGS.copy()

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
        self.shell_reader: Optional[Any] = None
        self.shell_writer: Optional[Any] = None
        self.command_history: list[str] = []
        self.history_index: int = -1
        self.log_worker = None
        self.log_update_timer = None
        self.shell_task = None
        self.shell_available = False
        self.shell_checked = False
        self.active_tab = "Logs"

    def compose(self):
        with TabbedContent():
            with TabPane("Logs", id="Logs"):
                with VerticalScroll(id="log-scroll", classes="log-container"):
                    yield Static("", id="log-output", classes="log-text")
                yield Input(
                    placeholder="🔍 Filter logs...",
                    id="log-filter",
                    classes="menu-input hidden",
                )

            with TabPane("Terminal", id="Terminal"):
                with VerticalScroll(id="shell-scroll", classes="shell-container"):
                    yield Static("", id="shell-output", classes="shell-text")
                yield Input(
                    placeholder="💻 Type shell command...",
                    id="shell-input",
                    classes="menu-input",
                )
        yield Footer()

    async def on_mount(self):
        self.set_focus(None)
        self.keep_streaming = True
        self.log_update_timer = self.set_interval(0.5, self.refresh_logs, name="log_ui")
        self.log_worker = self.run_worker(self.stream_logs, group="logs", thread=True)
        # Check if shell is available in the container
        self.check_shell_availability()

    def check_shell_availability(self):
        """Check if the container has a shell available."""
        async def _check():
            try:
                self.shell_available = await check_shell_availability(self.container_id)
                self.shell_checked = True
                
                # Update UI if we're on the terminal tab
                if self.query_one(TabbedContent).active == "Terminal":
                    self.update_terminal_ui()
            except Exception as e:
                print(f"Error checking shell: {e}")
                self.shell_available = False
                self.shell_checked = True
                if self.query_one(TabbedContent).active == "Terminal":
                    self.update_terminal_ui()
                    
        asyncio.create_task(_check())

    def update_terminal_ui(self):
        """Update the terminal UI based on shell availability."""
        shell_input = self.query_one("#shell-input", Input)
        shell_output = self.query_one("#shell-output", Static)
        
        if not self.shell_checked:
            shell_output.update("[yellow]Checking shell availability...[/yellow]")
            shell_input.disabled = True
            shell_input.placeholder = "⏳ Checking shell..."
        elif not self.shell_available:
            shell_output.update(
                "[red]No shell available in this container[/red]\n\n"
                "This container doesn't have a shell (sh, bash, etc.) available.\n"
                "You can still view the logs, but terminal access is not possible.\n\n"
                "Common reasons:\n"
                "• Container uses a minimal base image (like scratch)\n"
                "• Container is not running\n"
                "• Container has restricted permissions"
            )
            shell_input.disabled = True
            shell_input.placeholder = "❌ No shell available"
        else:
            shell_output.update("[green]Shell is available[/green]\n\nConnecting...")
            shell_input.disabled = False
            shell_input.placeholder = "💻 Type shell command..."
            # Auto-connect if not already connected
            if not self.shell_reader:
                self.action_open_shell()

    def focus_shell_input_if_needed(self):
        """Focus shell input if Terminal tab is active and shell is available."""
        if (self.query_one(TabbedContent).active == "Terminal" and 
            self.shell_available and not self.query_one("#shell-input").disabled):
            self.set_focus(self.query_one("#shell-input"))

    async def on_unmount(self) -> None:
        self.keep_streaming = False
        await _safe_close(self.shell_writer)
        self.shell_reader = None
        self.shell_writer = None
        if self.shell_task and not self.shell_task.done():
            self.shell_task.cancel()

    def on_key(self, event: Key) -> None:
        """Handle key press events."""
        # Get the active tab
        active_tab = self.query_one(TabbedContent).active

        # Handle tab-specific keyboard shortcuts
        if event.key == "/" and active_tab == "Logs":
            # Filter shortcut only in Logs tab
            event.prevent_default()
            self.action_focus_filter()
            return

        if event.key == "ctrl+l" and active_tab == "Terminal":
            # Clear shortcut only in Terminal tab
            event.prevent_default()
            self.action_clear_shell()
            return

        # Handle shell input only in Terminal tab
        shell_input = self.query_one("#shell-input", Input)
        if active_tab == "Terminal" and shell_input.has_focus and not shell_input.disabled:
            if event.key == "up":
                event.prevent_default()
                if self.command_history and self.history_index > 0:
                    self.history_index -= 1
                    shell_input.value = self.command_history[self.history_index]
                elif self.command_history and self.history_index == -1:
                    self.history_index = len(self.command_history) - 1
                    shell_input.value = self.command_history[self.history_index]
            elif event.key == "down":
                event.prevent_default()
                if self.command_history and self.history_index < len(self.command_history) - 1:
                    self.history_index += 1
                    shell_input.value = self.command_history[self.history_index]
                else:
                    self.history_index = -1
                    shell_input.value = ""
            elif event.key == "tab":
                event.prevent_default()
                # Basic tab completion
                current_input = shell_input.value
                if current_input and not current_input.isspace():
                    # Simple example: complete to common commands
                    common_commands = ["ls", "cd", "pwd", "cat", "echo", "ps", "grep"]
                    for cmd in common_commands:
                        if cmd.startswith(current_input):
                            shell_input.value = cmd
                            break

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input commands."""
        try:
            command = event.value.strip()
            input_widget = event.input
            input_widget.value = ""  # clear input box

            if not command:
                return

            # Reconnect if shell is closed
            if not self.shell_writer or self.shell_writer.is_closing():
                self.shell_lines.append("[yellow]Reconnecting shell...[/yellow]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
                try:
                    self.shell_reader, self.shell_writer = await open_docker_shell(self.container_id)
                    self.shell_lines.append(PROMPT)
                    asyncio.create_task(self.read_shell_output())
                except Exception as e:
                    self.shell_lines.append(f"[red]Failed to reconnect: {e}[/red]\n")
                    self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
                    return

            # Send clear command first
            self.shell_writer.write(("clear\n").encode())
            await self.shell_writer.drain()
            
            # Clear the terminal UI
            self.shell_lines.clear()
            self.shell_lines.append(f"{command}\n")  # Show the command at top
            self.shell_lines.append(PROMPT)
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))

            # Send the actual command
            try:
                self.shell_writer.write((command + "\n").encode())
                await self.shell_writer.drain()
                self.command_history.append(command)
                self.history_index = -1
            except Exception as e:
                self.shell_lines.insert(-1, f"[red]Error sending command: {e}[/red]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
        except Exception as e:
            pass

    def action_handle_escape(self) -> None:
        """Two-stage Escape behavior:
        1. Defocus input fields and hide filter
        2. Close container screen if already on tab menu
        """
        focused = self.focused
        log_filter = self.query_one("#log-filter")

        # Stage 1: If any input is focused, remove focus
        if focused and hasattr(focused, "id"):
            if focused.id == "log-filter":
                focused.add_class("hidden")
            # Clear focus and move to tab menu
            self.set_focus(None)
            return

        # Stage 2: If no input is focused, close screen
        self.app.pop_screen()

    def action_focus_filter(self) -> None:
        """Focus the filter input only in Logs tab."""
        if self.query_one(TabbedContent).active == "Logs":
            filter_input = self.query_one("#log-filter", Input)
            filter_input.remove_class("hidden")
            self.set_focus(filter_input)

    def action_clear_shell(self) -> None:
        """Clear the terminal only in Terminal tab."""
        if self.query_one(TabbedContent).active == "Terminal":
            self.shell_lines.clear()
            self.query_one("#shell-output", Static).update("")

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for filter and shell."""
        if event.input.id == "log-filter":
            # Update filter text and refresh logs
            self.filter_text = event.value.lower()
            self.refresh_logs()

    def refresh_logs(self):
        scroll_view = self.query_one("#log-scroll", VerticalScroll)
        log_output = self.query_one("#log-output", Static)

        at_bottom = scroll_view.scroll_y + scroll_view.size.height >= scroll_view.virtual_size.height - 1
        filtered = [
            self.colorize_log(line)
            for line in self.log_lines[-200:]
            if not self.filter_text or self.filter_text in line.lower()
        ]
        log_output.update("\n".join(filtered))
        if at_bottom:
            scroll_view.scroll_end(animate=False)

    def stream_logs(self):
        try:
            for line in stream_logs(self.container_id, follow=True, tail="100", timestamps=True):
                if not self.keep_streaming:
                    break
                line = line.decode(errors="ignore") if isinstance(line, bytes) else line
                self.log_lines.append(line)
                if len(self.log_lines) > 1000:
                    self.log_lines.pop(0)
        except Exception as e:
            self.log_lines.append(f"[red]Error streaming logs: {e}[/red]")

    
    async def read_shell_output(self):
        """Read shell output and update the terminal UI."""
        try:
            buffer = ""
            output_widget = self.query_one("#shell-output", Static)
            scroll_view = self.query_one("#shell-scroll", VerticalScroll)
            
            # Track if we're in a real-time updating command
            is_realtime_cmd = False
            realtime_output = []

            while self.shell_reader and not self.shell_reader.at_eof():
                data = await self.shell_reader.read(1024)
                if not data:
                    break

                decoded = data.decode(errors="ignore")
                buffer += decoded

                # Check for real-time updating commands (those using cursor movement)
                if "\x1B[H" in buffer or "\x1B[2J" in buffer:  # Clear screen or cursor home sequences
                    is_realtime_cmd = True
                    realtime_output = []
                    buffer = buffer.replace("\x1B[H", "").replace("\x1B[2J", "")

                # Process the buffer
                while "\n" in buffer or "\r" in buffer:
                    if "\r\n" in buffer:
                        line, buffer = buffer.split("\r\n", 1)
                        line_end = "\r\n"
                    elif "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line_end = "\n"
                    elif "\r" in buffer:
                        line, buffer = buffer.split("\r", 1)
                        line_end = "\r"
                    else:
                        break

                    clean_line = strip_vt100(line)
                    clean_line = expand_tabs(clean_line)

                    # Skip echoed command
                    if self.command_history and clean_line.strip() == self.command_history[-1]:
                        continue

                    if is_realtime_cmd:
                        realtime_output.append(clean_line + line_end)
                    else:
                        # Insert output above the prompt
                        if clean_line.strip():
                            self.shell_lines.insert(-1, clean_line + line_end)
                        else:
                            self.shell_lines.insert(-1, line_end)

                    # Update the display
                    if is_realtime_cmd:
                        # For real-time commands, replace the entire output
                        self.shell_lines = realtime_output + [PROMPT]
                        output_widget.update("".join(self.shell_lines))
                    else:
                        # For normal commands, append and scroll
                        at_bottom = scroll_view.scroll_y + scroll_view.size.height >= scroll_view.virtual_size.height - 1
                        output_widget.update("".join(self.shell_lines[-1000:]))
                        if at_bottom:
                            scroll_view.scroll_end(animate=False)

            # Append remaining buffer
            if buffer.strip():
                self.shell_lines.insert(-1, expand_tabs(strip_vt100(buffer)))
                output_widget.update("".join(self.shell_lines[-1000:]))

            self.shell_lines.append("[red]Shell session closed. Type a command to reconnect.[/red]\n")
            output_widget.update("".join(self.shell_lines[-1000:]))
            self.shell_reader = None
            self.shell_writer = None

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.shell_lines.append(f"[red]Error reading shell: {e}[/red]\n")
            self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))

    def action_open_shell(self) -> None:
        """Open a shell connection to the container."""
        if not self.shell_available:
            self.shell_lines.append("[red]No shell available in this container[/red]\n")
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))
            return

        async def _open():
            if self.shell_writer:
                await _safe_close(self.shell_writer)
                self.shell_reader = None
                self.shell_writer = None

            try:
                self.shell_lines.clear()
                self.shell_lines.append("[yellow]Connecting to shell...[/yellow]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines))

                self.shell_reader, self.shell_writer = await open_docker_shell(self.container_id)
                self.shell_lines.append("[green]Connected to shell[/green]\n")
                self.shell_lines.append(PROMPT)  # <-- Add prompt immediately
                self.query_one("#shell-output", Static).update("".join(self.shell_lines))

                if self.shell_task and not self.shell_task.done():
                    self.shell_task.cancel()
                self.shell_task = asyncio.create_task(self.read_shell_output())
                self.set_focus(self.query_one("#shell-input"))

            except Exception as e:
                error_msg = str(e)
                self.shell_lines.append(f"[red]Failed to connect: {error_msg}[/red]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines))
                if "no shell" in error_msg.lower() or "not running" in error_msg.lower():
                    self.shell_available = False
                    self.update_terminal_ui()

        asyncio.create_task(_open())


    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation."""
        if event.tab.id:
            self.active_tab = event.tab.id
            # Switch bindings based on active tab
            if event.tab.id == "Terminal":
                self.__class__.BINDINGS = self.TERMINAL_BINDINGS
            else:
                self.__class__.BINDINGS = self.LOGS_BINDINGS
            # Trigger bindings update
            self.notify_bindings_change()

        if event.tab.id == "Terminal":
            # Update UI based on shell availability
            if self.shell_checked:
                self.update_terminal_ui()
            # Focus input field after the tab switch is complete
            self.call_after_refresh(self.focus_shell_input_if_needed)
        else:
            # Remove focus from inputs when switching to other tabs
            self.set_focus(None)

    def notify_bindings_change(self) -> None:
        """Trigger a bindings update to show or hide tab-specific bindings."""
        footer = self.query_one(Footer)
        if footer:
            footer.refresh(layout=True)

    def action_do_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self.app.pop_screen()

    def action_switch_tab(self, tab: str) -> None:
        try:
            self.query_one(TabbedContent).active = tab
            if tab == "Terminal":
                self.call_after_refresh(self.action_open_shell)
        except Exception:
            self.app.bell()

    def colorize_log(self, line: str) -> str:
        escaped_line = re.sub(r"([\[\]])", r"\\\1", line)
        upper = escaped_line.upper()
        if "ERROR" in upper or "FATAL" in upper:
            return f"[red]{escaped_line}[/red]"
        elif "WARN" in upper:
            return f"[yellow]{escaped_line}[/yellow]"
        elif "INFO" in upper:
            return f"[green]{escaped_line}[/green]"
        elif "DEBUG" in upper:
            return f"[blue]{escaped_line}[/blue]"
        return escaped_line
        


