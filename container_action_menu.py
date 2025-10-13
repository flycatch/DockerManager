from widgets.confirm import ConfirmActionScreen
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
from tabs.container_info import InfoTab
async def _safe_close(writer: Optional[asyncio.StreamWriter]) -> None:
    """Safely close a StreamWriter if it exists.
    
    Args:
        writer: The StreamWriter to close. Can be None.
        
    This is a helper function that handles the safe closing of a StreamWriter,
    ensuring proper cleanup even if the writer is None or closing fails.
    """
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
    """Expand tabs to spaces with proper tab stops.
    
    Args:
        text: The input text containing tabs to expand
        tab_width: The number of spaces each tab should be expanded to. Defaults to TAB_WIDTH (8)
        
    Returns:
        str: The text with all tabs expanded to spaces, maintaining proper alignment
        
    This function replaces all tab characters with the appropriate number of spaces,
    taking into account the current column position to maintain proper alignment.
    """
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
    """Convert ANSI color codes to Textual markup.
    
    Args:
        ansi_code: The ANSI escape code string to convert (without the escape sequence prefix)
        
    Returns:
        str: The equivalent Textual markup tags for the given ANSI code
        
    Supports:
    - Basic formatting (bold, dim, underline)
    - Foreground colors (30-37)
    - Background colors (40-47)
    - Reset code (0)
    
    Example:
        '31;1' -> '[red][bold]'
        '0' -> '[/]'
    """
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
    """Remove VT100 escape sequences but preserve some formatting.
    
    Args:
        text: The input text containing VT100 escape sequences
        
    Returns:
        str: Text with VT100 sequences converted to Textual markup
        
    This function handles:
    - Removal of non-color escape sequences
    - Conversion of color sequences to Textual markup
    - Preservation of important formatting while removing unwanted control sequences
    - Special handling for color combinations and text attributes
    
    Example:
        '\x1B[31mError\x1B[0m' -> '[red]Error[/]'
    """
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
        Binding("left", "switch_tab_prev", "Previous Tab"),
        Binding("right", "switch_tab_next", "Next Tab"),
        Binding("escape", "handle_escape", "Close", key_display="ESC"),
        Binding("j", "scroll_down_universal", "Scroll Down", show=False),
        Binding("k", "scroll_up_universal", "Scroll Up", show=False),
    ]
    
    LOGS_BINDINGS: List[BindingType] = COMMON_BINDINGS + [
        Binding("/", "focus_filter", "Filter Logs"),
        Binding("s", "do_action('start')", "Start"),
        Binding("p", "do_action('stop')", "Stop"),
        # Delete binding removed
    ]


    TERMINAL_BINDINGS: List[BindingType] = COMMON_BINDINGS + [
        Binding("ctrl+l", "clear_shell", "Clear Shell"),
    ]

    # Start with logs bindings since Logs is the default tab
    BINDINGS: List[BindingType] = LOGS_BINDINGS.copy()

    class Selected(Message):
        """Message emitted when a container action is selected.
        
        This message is sent when the user selects an action (start/stop/delete)
        to be performed on the container.
        
        Attributes:
            action: The name of the action to perform ('start', 'stop', or 'delete')
            container_id: The ID of the container to perform the action on
        """
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
        """Compose the UI layout of the container action screen.
        
        Creates a tabbed interface with two tabs:
        1. Logs Tab:
           - Log output area with scrolling
           - Filter input (hidden by default)
           
        2. Terminal Tab:
           - Shell output area with scrolling
           - Shell input field
        
        Also adds a footer with keybindings.
        """
        with TabbedContent():
            with TabPane("Info", id="info-tab"):
                yield InfoTab(self.container_id)
                
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
        """Initialize the screen on mounting.
        
        This method:
        1. Clears any focus
        2. Starts the log streaming
        3. Sets up periodic log UI updates
        4. Checks shell availability
        """
        self.set_focus(None)
        self.keep_streaming = True
        self.log_update_timer = self.set_interval(0.5, self.refresh_logs, name="log_ui")
        self.log_worker = self.run_worker(self.stream_logs, group="logs", thread=True)
        # Check if shell is available in the container
        self.check_shell_availability()
        await self.load_container_info()
        try:
            tc = self.query_one(TabbedContent)
            tc.active = "Logs"
            self.active_tab = "Logs"
            # Make sure footer shows Logs bindings
            self.__class__.BINDINGS = self.LOGS_BINDINGS
            self.notify_bindings_change()
            # Focus the log scroll area after the UI refresh completes
            self.call_after_refresh(lambda: self.set_focus(self.query_one("#log-scroll")))
        except Exception:
            # don't crash mount if something goes wrong
            pass        

    async def load_container_info(self):
        """Load container info - the InfoTab will handle its own data loading."""
        pass
    
    def action_scroll_down_universal(self) -> None:
        """Scroll down by one line in the active tab (j key)."""
        active_tab = self.query_one(TabbedContent).active
        
        if active_tab == "Logs":
            scroll_view = self.query_one("#log-scroll", VerticalScroll)
            scroll_view.scroll_down(animate=True)
        elif active_tab == "Terminal":
            # Only scroll if input is not focused
            if not self.query_one("#shell-input").has_focus:
                scroll_view = self.query_one("#shell-scroll", VerticalScroll)
                scroll_view.scroll_down(animate=True)
        elif active_tab == "info-tab":
            # Try to find a scrollable container inside InfoTab
            try:
                # Option A: If InfoTab has a specific scroll container ID
                scroll_view = self.query_one("#info-scroll", VerticalScroll)
                scroll_view.scroll_down(animate=True)
            except:
                # Option B: Find any VerticalScroll or ScrollableContainer in InfoTab
                try:
                    info_tab = self.query_one(InfoTab)
                    scroll_view = info_tab.query_one(VerticalScroll)
                    scroll_view.scroll_down(animate=True)
                except:
                    # Option C: Scroll the InfoTab itself (if it extends ScrollView)
                    info_tab = self.query_one(InfoTab)
                    info_tab.scroll_down(animate=True)

    def action_scroll_up_universal(self) -> None:
        """Scroll up by one line in the active tab (k key)."""
        active_tab = self.query_one(TabbedContent).active
        
        if active_tab == "Logs":
            scroll_view = self.query_one("#log-scroll", VerticalScroll)
            scroll_view.scroll_up(animate=True)
        elif active_tab == "Terminal":
            # Only scroll if input is not focused
            if not self.query_one("#shell-input").has_focus:
                scroll_view = self.query_one("#shell-scroll", VerticalScroll)
                scroll_view.scroll_up(animate=True)
        elif active_tab == "info-tab":
            # Try to find a scrollable container inside InfoTab
            try:
                # Option A: If InfoTab has a specific scroll container ID
                scroll_view = self.query_one("#info-scroll", VerticalScroll)
                scroll_view.scroll_up(animate=True)
            except:
                # Option B: Find any VerticalScroll or ScrollableContainer in InfoTab
                try:
                    info_tab = self.query_one(InfoTab)
                    scroll_view = info_tab.query_one(VerticalScroll)
                    scroll_view.scroll_up(animate=True)
                except:
                    # Option C: Scroll the InfoTab itself (if it extends ScrollView)
                    info_tab = self.query_one(InfoTab)
                    info_tab.scroll_up(animate=True)


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
                # Schedule async shell connection properly
                asyncio.create_task(self.action_open_shell())


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
        """Handle key press events, including tab switching and shell input navigation."""
        active_tab = self.query_one(TabbedContent).active
        shell_input = self.query_one("#shell-input", Input)

        # Allow left/right tab switching even if shell input is focused, unless text is selected
        if event.key in ("left", "right") and active_tab == "Terminal" and shell_input.has_focus and not shell_input.disabled:
            # If input has a selection, let left/right move the cursor
            if hasattr(shell_input, "selection") and shell_input.selection and shell_input.selection[0] != shell_input.selection[1]:
                return
            # Otherwise, switch tabs
            if event.key == "left":
                self.action_switch_tab_prev()
                event.prevent_default()
                return
            elif event.key == "right":
                self.action_switch_tab_next()
                event.prevent_default()
                return

        # Handle tab-specific keyboard shortcuts
        if event.key == "/" and active_tab == "Logs":
            event.prevent_default()
            self.action_focus_filter()
            return

        if event.key == "ctrl+l" and active_tab == "Terminal":
            event.prevent_default()
            self.action_clear_shell()
            return

        # Handle shell input navigation only if shell input is focused in Terminal tab
        if active_tab == "Terminal" and shell_input.has_focus and not shell_input.disabled:
            if event.key == "up":
                if self.command_history:
                    if self.history_index == -1:
                        self.history_index = len(self.command_history) - 1
                    elif self.history_index > 0:
                        self.history_index -= 1
                    shell_input.value = self.command_history[self.history_index]
            elif event.key == "down":
                if self.command_history:
                    if self.history_index < len(self.command_history) - 1:
                        self.history_index += 1
                        shell_input.value = self.command_history[self.history_index]
                    else:
                        self.history_index = -1
                        shell_input.value = ""
            elif event.key == "tab":
                pass

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle submitted shell commands.
        
        Args:
            event: The submission event containing the command text
            
        This method:
        1. Handles shell reconnection if needed
        2. Clears the terminal UI
        3. Sends the command to the shell
        4. Updates command history
        5. Handles any errors during command execution
        
        The terminal is automatically cleared before each command to maintain
        a clean view of command output.
        """
        try:
            command = event.value.strip()
            input_widget = event.input
            input_widget.value = ""  # clear input box

            if not command:
                return

            # Handle reconnection if needed
            if not self.shell_writer or self.shell_writer.is_closing():
                self.shell_lines.append("[yellow]Reconnecting shell...[/yellow]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
                try:
                    # Clean up old connection if it exists
                    if self.shell_writer:
                        await _safe_close(self.shell_writer)
                        self.shell_reader = None
                        self.shell_writer = None
                    if self.shell_task and not self.shell_task.done():
                        self.shell_task.cancel()
                        self.shell_task = None
                    
                    # Establish new connection
                    self.shell_reader, self.shell_writer = await open_docker_shell(self.container_id)
                    self.shell_lines.append("[green]Shell reconnected successfully[/green]\n")
                    self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
                    
                    # Start new shell output reader task
                    self.shell_task = asyncio.create_task(self.read_shell_output())
                except Exception as e:
                    self.shell_lines.append(f"[red]Failed to reconnect: {e}[/red]\n")
                    self.query_one("#shell-output", Static).update("".join(self.shell_lines[-1000:]))
                    if "no shell" in str(e).lower() or "not running" in str(e).lower():
                        self.shell_available = False
                        self.update_terminal_ui()
                    return

                # Handle 'exit' command specially
            if command.lower() == 'exit':
                self.shell_lines.append("[yellow]Closing shell session...[/yellow]\n")
                self.query_one("#shell-output", Static).update("".join(self.shell_lines))
                await _safe_close(self.shell_writer)
                self.shell_reader = None
                self.shell_writer = None
                if self.shell_task and not self.shell_task.done():
                    self.shell_task.cancel()
                    self.shell_task = None
                return
                
            # Send clear command first
            self.shell_writer.write(("clear\n").encode())
            await self.shell_writer.drain()
            
            # Clear the terminal UI
            self.shell_lines.clear()
            self.shell_lines.append(f"{command}\n")  # Show the command at top
            self.shell_lines.append(PROMPT)
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))            # Send the actual command
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
        """ESC always closes the screen immediately."""
        focused = self.focused
        log_filter = self.query_one("#log-filter")
        if focused and hasattr(focused, "id"):
            if focused.id == "log-filter":
                focused.add_class("hidden")
            self.set_focus(None)
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
        """Update the logs display with filtered and colorized content.
        
        This method:
        1. Applies the current filter text to log lines
        2. Colorizes log entries based on log level
        3. Maintains scroll position
        4. Shows only the last 200 matching lines
        5. Auto-scrolls to bottom if already at bottom
        """
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
        """Stream container logs in a background thread.
        
        This method:
        1. Connects to the container's log stream
        2. Retrieves the last 100 log lines initially
        3. Continuously receives new log lines
        4. Maintains a rolling buffer of 1000 lines
        5. Handles stream interruption and errors
        
        The logs are automatically timestamped and can be filtered in the UI.
        """
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
        """Read shell output and update the terminal UI.
        
        This method continuously reads from the shell connection and updates the UI:
        1. Handles different line ending types (\\n, \\r\\n, \\r)
        2. Processes VT100 escape sequences
        3. Expands tabs to spaces
        4. Handles real-time updating commands (like top)
        5. Manages command echo suppression
        6. Maintains scroll position
        
        Special handling is provided for:
        - Real-time updating commands (using cursor movement)
        - Buffer management to handle partial reads
        - Automatic scroll-to-bottom when at bottom
        """
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
                            # Keep buffer size in check by removing oldest lines if needed
                            if len(self.shell_lines) > 1000:
                                self.shell_lines = self.shell_lines[-900:]  # Keep last 900 lines
                                self.shell_lines.append("[dim]... older output truncated ...[/dim]\n")
                            
                            # Add the new line just before the prompt
                            self.shell_lines.insert(-1, clean_line + line_end)
                        else:
                            # Handle empty lines to maintain formatting
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

    async def action_open_shell(self) -> None:
        """Open an interactive shell connection to the container."""
        if not self.shell_available:
            self.shell_lines.append("[red]No shell available in this container[/red]\n")
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))
            return

        # Clean up any previous connection
        if self.shell_writer:
            await _safe_close(self.shell_writer)
            self.shell_reader = None
            self.shell_writer = None

        try:
            # Show connecting message
            self.shell_lines.clear()
            self.shell_lines.append("[yellow]Connecting to shell...[/yellow]\n")
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))

            # Open new shell
            self.shell_reader, self.shell_writer = await open_docker_shell(self.container_id)

            # Update UI
            self.shell_lines.append("[green]Connected to shell[/green]\n")
            self.shell_lines.append(PROMPT)  # Show prompt
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))

            # Cancel previous shell reader task if exists
            if self.shell_task and not self.shell_task.done():
                self.shell_task.cancel()

            # Start reading shell output
            self.shell_task = asyncio.create_task(self.read_shell_output())

            # Focus input
            self.set_focus(self.query_one("#shell-input"))

        except Exception as e:
            error_msg = str(e)
            self.shell_lines.append(f"[red]Failed to connect: {error_msg}[/red]\n")
            self.query_one("#shell-output", Static).update("".join(self.shell_lines))
            if "no shell" in error_msg.lower() or "not running" in error_msg.lower():
                self.shell_available = False
                self.update_terminal_ui()



    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Handle tab activation."""
        if not event.tab.id:
            return

        self.active_tab = event.tab.id
        self.notify_bindings_change()

        if event.tab.id == "Terminal":
            if self.shell_checked:
                self.update_terminal_ui()
            self.call_after_refresh(self.focus_shell_input_if_needed)
        elif event.tab.id == "Info":
            self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))
        else:  # Logs
            self.set_focus(None)


    def notify_bindings_change(self) -> None:
        """Update footer keybindings based on active tab, avoiding duplicates."""
        footer = self.query_one(Footer)
        active_tab = self.active_tab if hasattr(self, "active_tab") else None
        # Always start with only common bindings
        bindings = self.COMMON_BINDINGS.copy()
        if active_tab == "Logs":
            for b in self.LOGS_BINDINGS:
                if b not in bindings and b not in self.COMMON_BINDINGS:
                    bindings.append(b)
        elif active_tab == "Terminal":
            for b in self.TERMINAL_BINDINGS:
                if b not in bindings and b not in self.COMMON_BINDINGS:
                    bindings.append(b)
        self.__class__.BINDINGS = bindings
        if footer:
            footer.refresh(layout=True)

    def action_do_action(self, action_name: str):
        if action_name in ("start", "stop"):
            self.app.push_screen(ConfirmActionScreen(
                f"{action_name.capitalize()} container '{self.container_name}'? (Y/n)",
                lambda confirmed: self._do_container_action(action_name) if confirmed else None
            ))
        elif action_name == "restart":
            self.app.push_screen(ConfirmActionScreen(
                f"Restart container '{self.container_name}'? (Y/n)",
                lambda confirmed: self._do_container_action(action_name) if confirmed else None
            ))
        # Delete action removed

    def _do_container_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self.app.pop_screen()

    def _pane_identity(self, pane: Any, index: int) -> str:
        """Return a stable identifier for a TabPane: prefer id, then label/title, else synthetic."""
        pid = getattr(pane, "id", None)
        if pid:
            return str(pid)
        label = getattr(pane, "label", None) or getattr(pane, "title", None)
        if label:
            return str(label)
        return f"__pane_{index}"


    def _find_current_index(self, tc: TabbedContent, panes: list[Any]) -> int:
        """
        Robustly find the active pane index, matching on:
        - tc.active == pane.id (most common)
        - tc.active == pane.label/title
        - tc.active is the pane object itself
        Fallback: 0
        """
        active = tc.active
        for i, p in enumerate(panes):
            pid = getattr(p, "id", None)
            label = getattr(p, "label", None) or getattr(p, "title", None)
            if isinstance(active, str):
                if pid == active or label == active:
                    return i
            else:
                # tc.active might be the pane object itself
                if active is p:
                    return i
        return 0


    def action_switch_tab_prev(self) -> None:
        """Switch to the previous tab (wraps around)."""
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return

            cur_idx = self._find_current_index(tc, panes)
            prev_idx = cur_idx - 1
            if prev_idx < 0:
                prev_idx = len(panes) - 1  # wrap to last

            pane = panes[prev_idx]
            new_active = getattr(pane, "id", None) or getattr(pane, "label", None) or getattr(pane, "title", None) or str(prev_idx)
            tc.active = str(new_active)

            # post-switch behavior
            if tc.active == "Terminal":
                self.call_after_refresh(self.action_open_shell)
            elif tc.active == "Info":
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))

        except Exception:
            self.app.bell()


    def action_switch_tab_next(self) -> None:
        """Switch to the next tab (wraps around)."""
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return

            cur_idx = self._find_current_index(tc, panes)
            next_idx = cur_idx + 1
            if next_idx >= len(panes):
                next_idx = 0  # wrap to first

            pane = panes[next_idx]
            new_active = getattr(pane, "id", None) or getattr(pane, "label", None) or getattr(pane, "title", None) or str(next_idx)
            tc.active = str(new_active)

            # post-switch behavior
            if tc.active == "Terminal":
                self.call_after_refresh(self.action_open_shell)
            elif tc.active == "Info":
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))

        except Exception:
            self.app.bell()


    def action_switch_tab(self, tab: str) -> None:
        """
        Switch to a tab by id or label. Safe and triggers terminal open / info refresh when needed.
        """
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return

            # If already active, nothing to do
            if isinstance(tc.active, str) and tc.active == tab:
                return

            # Try matching by id first, then label/title
            matched_id = None
            for i, p in enumerate(panes):
                pid = getattr(p, "id", None)
                label = getattr(p, "label", None) or getattr(p, "title", None)
                if pid == tab:
                    matched_id = str(pid)
                    break
                if label == tab:
                    matched_id = str(pid or label)
                    break

            if matched_id:
                tc.active = matched_id
            else:
                # If the provided tab looks like an id that we don't know, try to set it directly
                # (Textual may accept it), otherwise ring bell.
                try:
                    tc.active = str(tab)
                except Exception:
                    self.app.bell()
                    return

            # After switching behavior
            if tc.active == "Terminal":
                self.call_after_refresh(self.action_open_shell)
            elif tc.active == "Info":
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))

        except Exception:
            self.app.bell()


    def colorize_log(self, line: str) -> str:
        """Apply color formatting to log lines based on log level.
        
        Args:
            line: The log line to colorize
            
        Returns:
            str: The log line with Textual markup for colors based on log level:
                - Red: ERROR or FATAL
                - Yellow: WARN
                - Green: INFO
                - Blue: DEBUG
                
        Also escapes any existing square brackets in the text to prevent
        interference with Textual markup.
        """
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



