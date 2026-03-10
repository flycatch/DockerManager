# container_action_menu.py
from widgets.confirm import ConfirmActionScreen
from textual.screen import ModalScreen
from textual.widgets import Static, Input, Footer, TabbedContent, TabPane
from textual.message import Message
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.events import Key
from typing import List, Any
import asyncio
import time
import re
from container_logs import stream_logs
from tabs.container_info import InfoTab
from tabs.container_stats import StatsTab
from container_exec import ContainerShell


class ContainerActionScreen(ModalScreen):
    CSS_PATH = "tcss/shell.tcss"
    COMMON_BINDINGS: List[BindingType] = [
        Binding("shift+left", "switch_tab_prev", "Previous Tab", priority=True),
        Binding("shift+right", "switch_tab_next", "Next Tab", priority=True),
        Binding("escape", "handle_escape", "Close", key_display="ESC"),
        Binding("u", "do_action('start')", "Start"),
        Binding("d", "do_action('stop')", "Stop"),
        Binding("r", "do_action('restart')", "Restart"),
    ]
    
    LOGS_BINDINGS: List[BindingType] = COMMON_BINDINGS + [
        Binding("/", "focus_filter", "Filter Logs"),
        Binding("n", "next_match", "Next Match"),
        Binding("N", "prev_match", "Prev Match"),
    ]
    
    TERMINAL_BINDINGS: List[BindingType] = [
        Binding("shift+left", "switch_tab_prev", "Previous Tab", priority=True),
        Binding("shift+right", "switch_tab_next", "Next Tab", priority=True),
        Binding("escape", "handle_escape", "Close", key_display="ESC"),
    ]
    
    INFO_BINDINGS: List[BindingType] = COMMON_BINDINGS.copy()
    STATS_BINDINGS: List[BindingType] = COMMON_BINDINGS.copy()
    
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
        self.keep_streaming = False
        self.filter_text = ""
        self.log_worker = None
        self.log_update_timer = None
        self.active_tab = "Logs"
        self.log_matches: list[dict] = []
        self.current_match: int = -1
        # timestamp of last tab activation handled here; used to suppress
        # noisy notify_bindings_change calls that race with TabActivated.
        self._last_activation: float = 0.0
        self._initializing_tabs = True
    
    def compose(self):
        with TabbedContent():
            with TabPane("Info", id="info-tab"):
                yield InfoTab(self.container_id)
            with TabPane("Stats", id="stats-tab"):
                yield StatsTab(self.container_id)
            with TabPane("Logs", id="Logs"):
                with VerticalScroll(id="log-scroll", classes="log-container"):
                    yield Static("", id="log-output", classes="log-text")
                yield Input(
                    placeholder="🔍 Filter logs...",
                    id="log-filter",
                    classes="menu-input hidden",
                )
            with TabPane("Terminal", id="terminal-tab"):
                yield ContainerShell(self.container_id)
        yield Footer()
    
    async def on_mount(self):
        self.set_focus(None)
        self.keep_streaming = True
        self.log_update_timer = self.set_interval(0.5, self.refresh_logs, name="log_ui")
        self.log_worker = self.run_worker(self.stream_logs, group="logs", thread=True)
        await self.load_container_info()
        try:
            self.active_tab = "Logs"
            self._apply_bindings(self.LOGS_BINDINGS)
            self.call_after_refresh(self._activate_default_logs_tab)
        except Exception:
            pass        
        
    async def load_container_info(self):
        pass

    def _activate_default_logs_tab(self) -> None:
        try:
            tc = self.query_one(TabbedContent)
            self._initializing_tabs = False
            tc.active = "Logs"
            self.active_tab = "logs"
            self._apply_bindings(self.LOGS_BINDINGS)
            self._set_stats_refresh(False)
            self._focus_logs_tab()
        except Exception:
            self._initializing_tabs = False

    def _active_tab_kind(self) -> str:
        """Normalize active tab identity to a stable value."""
        try:
            active = self.query_one(TabbedContent).active
        except Exception:
            active = None
        active_s = str(active or "").lower()
        if active_s in ("logs", "log") or "log" in active_s:
            return "logs"
        if active_s in ("info", "info-tab") or "info" in active_s:
            return "info"
        if active_s in ("stats", "stats-tab") or "stats" in active_s:
            return "stats"
        if active_s in ("terminal", "terminal-tab") or "terminal" in active_s:
            return "terminal"
        if self.active_tab in ("Logs", "logs", "log"):
            return "logs"
        if self.active_tab in ("Info", "info-tab", "info"):
            return "info"
        if self.active_tab in ("Stats", "stats-tab", "stats"):
            return "stats"
        if self.active_tab in ("Terminal", "terminal-tab", "terminal"):
            return "terminal"
        return "unknown"

    def action_scroll_down_universal(self) -> None:
        tab_kind = self._active_tab_kind()
        if tab_kind == "logs":
            scroll_view = self.query_one("#log-scroll", VerticalScroll)
            scroll_view.scroll_down(animate=True)
            self.set_focus(scroll_view)
        elif tab_kind in ("info", "stats"):
            try:
                scroll_id = "#info-scroll" if tab_kind == "info" else "#stats-scroll"
                scroll_view = self.query_one(scroll_id, VerticalScroll)
                scroll_view.scroll_down(animate=True)
                self.set_focus(scroll_view)
            except:
                try:
                    tab_widget = self.query_one(InfoTab if tab_kind == "info" else StatsTab)
                    scroll_view = tab_widget.query_one(VerticalScroll)
                    scroll_view.scroll_down(animate=True)
                    self.set_focus(scroll_view)
                except:
                    tab_widget = self.query_one(InfoTab if tab_kind == "info" else StatsTab)
                    tab_widget.scroll_down(animate=True)

    def action_scroll_up_universal(self) -> None:
        tab_kind = self._active_tab_kind()
        if tab_kind == "logs":
            scroll_view = self.query_one("#log-scroll", VerticalScroll)
            scroll_view.scroll_up(animate=True)
            self.set_focus(scroll_view)
        elif tab_kind in ("info", "stats"):
            try:
                scroll_id = "#info-scroll" if tab_kind == "info" else "#stats-scroll"
                scroll_view = self.query_one(scroll_id, VerticalScroll)
                scroll_view.scroll_up(animate=True)
                self.set_focus(scroll_view)
            except:
                try:
                    tab_widget = self.query_one(InfoTab if tab_kind == "info" else StatsTab)
                    scroll_view = tab_widget.query_one(VerticalScroll)
                    scroll_view.scroll_up(animate=True)
                    self.set_focus(scroll_view)
                except:
                    tab_widget = self.query_one(InfoTab if tab_kind == "info" else StatsTab)
                    tab_widget.scroll_up(animate=True)

    async def on_unmount(self) -> None:
        self.keep_streaming = False
        self._restore_app_bindings()

    def _refresh_footer(self) -> None:
        try:
            footer = self.query_one(Footer)
            footer.refresh()
            self.refresh()
        except Exception:
            pass

    def _apply_bindings(self, bindings: List[BindingType]) -> None:
        self.BINDINGS = list(bindings)
        self._refresh_footer()

    def _restore_app_bindings(self) -> None:
        self._refresh_footer()

    def on_key(self, event: Key) -> None:
        tab_kind = self._active_tab_kind()
        if event.key == "shift+left":
            self.action_switch_tab_prev()
            event.prevent_default()
            return
        if event.key == "shift+right":
            self.action_switch_tab_next()
            event.prevent_default()
            return
        if event.key in ("up", "down") and tab_kind in ("logs", "info", "stats"):
            focused = self.focused
            if not (isinstance(focused, Input) and focused.id == "log-filter"):
                if event.key == "up":
                    self.action_scroll_up_universal()
                else:
                    self.action_scroll_down_universal()
                event.prevent_default()
                return
        if event.key == "/" and tab_kind == "logs":
            event.prevent_default()
            self.action_focus_filter()
            return
        if tab_kind == "logs" and event.key in ("n", "N"):
            if not self.log_matches:
                self.app.bell()
                return
            if event.key == "n":
                self.current_match = (self.current_match + 1) % len(self.log_matches) if self.current_match >= 0 else 0
            else:
                if self.current_match <= 0:
                    self.current_match = len(self.log_matches) - 1
                else:
                    self.current_match = (self.current_match - 1) % len(self.log_matches)
            self.focus_current_match()
            event.prevent_default()
            return

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            command = event.value.strip()
            input_widget = event.input
            if input_widget.id == "log-filter":
                self.filter_text = command.lower()
                self.log_matches = []
                if self.filter_text:
                    ft = self.filter_text
                    recent = self.log_lines[-200:]
                    filtered_lines = [
                        (i, line) for i, line in enumerate(recent) if self.filter_text in line.lower()
                    ]
                    for idx, (_, line) in enumerate(filtered_lines):
                        low = line.lower()
                        start = 0
                        while True:
                            pos = low.find(ft, start)
                            if pos == -1:
                                break
                            abs_index = filtered_lines[idx][0]
                            self.log_matches.append({"line_index": abs_index, "start": pos, "end": pos + len(ft)})
                            start = pos + len(ft)
                self.current_match = len(self.log_matches) - 1 if self.log_matches else -1
                try:
                    input_widget.add_class("hidden")
                except Exception:
                    pass
                self.set_focus(None)
                self.refresh_logs()
                if self.current_match != -1:
                    self.focus_current_match()
        except Exception as e:
            pass

    def action_handle_escape(self) -> None:
        focused = self.focused
        log_filter = self.query_one("#log-filter")
        if focused and hasattr(focused, "id"):
            if focused.id == "log-filter":
                focused.add_class("hidden")
            self.set_focus(None)
        self._restore_app_bindings()
        self.app.pop_screen()

    def action_focus_filter(self) -> None:
        if self._active_tab_kind() == "logs":
            filter_input = self.query_one("#log-filter", Input)
            filter_input.remove_class("hidden")
            self.set_focus(filter_input)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log-filter":
            self.filter_text = event.value.lower()
            self.refresh_logs()

    def refresh_logs(self):
        scroll_view = self.query_one("#log-scroll", VerticalScroll)
        log_output = self.query_one("#log-output", Static)
        at_bottom = scroll_view.scroll_y + scroll_view.size.height >= scroll_view.virtual_size.height - 1
        recent = self.log_lines[-200:]
        self.log_matches = []
        matches_by_line: dict[int, list[tuple[int,int,int]]] = {}
        if self.filter_text:
            ft = self.filter_text
            match_index = 0
            for idx, line in enumerate(recent):
                low = line.lower()
                start = 0
                while True:
                    pos = low.find(ft, start)
                    if pos == -1:
                        break
                    self.log_matches.append({"line_index": idx, "start": pos, "end": pos + len(ft)})
                    matches_by_line.setdefault(idx, []).append((pos, pos + len(ft), match_index))
                    match_index += 1
                    start = pos + len(ft)
        if self.current_match >= len(self.log_matches):
            self.current_match = -1
        rendered: list[str] = []
        for i, line in enumerate(recent):
            spans: list[tuple[int,int,bool]] = []
            if i in matches_by_line:
                for s, e, midx in matches_by_line[i]:
                    is_current = (midx == self.current_match)
                    spans.append((s, e, is_current))
            if spans:
                rendered.append(self.colorize_log(line, spans))
            else:
                rendered.append(self.colorize_log(line, None))
        log_output.update("\n".join(rendered))
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

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = str(getattr(event.tab, "id", "") or "").lower()
        tab_label = str(getattr(event.tab, "label", None) or getattr(event.tab, "title", None) or "").lower()
        if "info" in tab_id or tab_label == "info":
            tab_kind = "info"
        elif "stats" in tab_id or tab_label == "stats":
            tab_kind = "stats"
        elif "terminal" in tab_id or tab_label == "terminal":
            tab_kind = "terminal"
        elif "log" in tab_id or tab_label == "logs":
            tab_kind = "logs"
        else:
            tab_kind = self._active_tab_kind()

        if self._initializing_tabs and tab_kind != "logs":
            return

        self.active_tab = tab_kind

        self._set_stats_refresh(tab_kind == "stats")

        # Determine bindings directly from the TabPane in the event. Using
        # TabbedContent.active inside notify_bindings_change can be racy when
        # the TabActivated event fires (it may not have been updated yet), so
        # set bindings here based on the pane identity from the event.
        if tab_kind == "info":
            bindings = self.INFO_BINDINGS.copy()
        elif tab_kind == "stats":
            bindings = self.STATS_BINDINGS.copy()
        elif tab_kind == "terminal":
            bindings = self.TERMINAL_BINDINGS.copy()
        elif tab_kind == "logs":
            bindings = self.COMMON_BINDINGS.copy()
            for b in self.LOGS_BINDINGS:
                if b not in bindings and b not in self.COMMON_BINDINGS:
                    bindings.append(b)
        else:
            bindings = self.COMMON_BINDINGS.copy()

        # Apply bindings and record activation time to avoid notify races.
        self._apply_bindings(bindings)
        self._last_activation = time.time()

        # Now perform tab-specific actions (load info or focus terminal)
        if tab_kind == "info":
            self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))
<<<<<<< Updated upstream
        elif tab_id in ("terminal-tab",) or tab_label == "Terminal":
            self.call_after_refresh(lambda: self.set_focus(self.query_one("#container-terminal")))
        else:
            self.set_focus(None)

=======
            self.call_after_refresh(self._focus_info_tab)
        elif tab_kind == "stats":
            self.call_after_refresh(self._focus_stats_tab)
        elif tab_kind == "terminal":
            self.call_after_refresh(self._focus_terminal_tab)
        elif tab_kind == "logs":
            self.call_after_refresh(self._focus_logs_tab)

    def _focus_logs_tab(self) -> None:
        try:
            self.set_focus(self.query_one("#log-scroll", VerticalScroll))
        except Exception:
            self.set_focus(None)

    def _focus_info_tab(self) -> None:
        try:
            self.set_focus(self.query_one("#info-scroll", VerticalScroll))
            return
        except Exception:
            pass
        try:
            info_tab = self.query_one(InfoTab)
            self.set_focus(info_tab.query_one(VerticalScroll))
        except Exception:
            self.set_focus(None)

    def _focus_stats_tab(self) -> None:
        try:
            stats_tab = self.query_one(StatsTab)
            stats_tab.start_refresh()
            self.set_focus(self.query_one("#stats-scroll", VerticalScroll))
            return
        except Exception:
            pass
        try:
            stats_tab = self.query_one(StatsTab)
            stats_tab.start_refresh()
            self.set_focus(stats_tab.query_one(VerticalScroll))
        except Exception:
            self.set_focus(None)

    def _set_stats_refresh(self, enabled: bool) -> None:
        try:
            stats_tab = self.query_one(StatsTab)
        except Exception:
            return
        if enabled:
            stats_tab.start_refresh()
        else:
            stats_tab.stop_refresh()

    def _focus_terminal_tab(self) -> None:
        try:
            shell = self.query_one(ContainerShell)
            shell.ensure_started()
            self.set_focus(self.query_one("#container-terminal"))
        except Exception:
            self.app.bell()

>>>>>>> Stashed changes
    def notify_bindings_change(self) -> None:
        try:
            if getattr(self, "_last_activation", 0) and (time.time() - self._last_activation) < 0.05:
                return
        except Exception:
            pass
        active_tab = getattr(self, "active_tab", None)
        if not active_tab:
            try:
                tc = self.query_one(TabbedContent)
                panes = list(tc.query(TabPane))
                active = tc.active
                for p in panes:
                    pid = getattr(p, "id", None)
                    label = getattr(p, "label", None) or getattr(p, "title", None)
                    if isinstance(active, str):
                        if pid == active or label == active:
                            active_tab = label or pid
                            break
                    else:
                        if active is p:
                            active_tab = label or pid
                            break
            except Exception:
                active_tab = None

        if active_tab in ("Logs", "log", "logs"):
            bindings = self.COMMON_BINDINGS.copy()
            for b in self.LOGS_BINDINGS:
                if b not in bindings and b not in self.COMMON_BINDINGS:
                    bindings.append(b)
        elif active_tab in ("Stats", "stats", "stats-tab"):
            bindings = self.STATS_BINDINGS.copy()
        elif active_tab in ("Terminal", "terminal", "terminal-tab"):
            bindings = self.TERMINAL_BINDINGS.copy()
        elif active_tab in ("Info", "info", "info-tab"):
            bindings = self.INFO_BINDINGS.copy()
        else:
            bindings = self.COMMON_BINDINGS.copy()
        self._apply_bindings(bindings)

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

    def _do_container_action(self, action_name: str):
        self.post_message(self.Selected(action_name, self.container_id))
        self._restore_app_bindings()
        self.app.pop_screen()

    # Utility methods for tab switching (unchanged from your source)
    def _pane_identity(self, pane: Any, index: int) -> str:
        pid = getattr(pane, "id", None)
        if pid:
            return str(pid)
        label = getattr(pane, "label", None) or getattr(pane, "title", None)
        if label:
            return str(label)
        return f"__pane_{index}"

    def _pane_kind(self, pane: Any) -> str:
        pid = str(getattr(pane, "id", "") or "").lower()
        label = str(getattr(pane, "label", None) or getattr(pane, "title", None) or "").lower()
        if "info" in pid or label == "info":
            return "info"
        if "stats" in pid or label == "stats":
            return "stats"
        if "terminal" in pid or label == "terminal":
            return "terminal"
        if "log" in pid or label == "logs":
            return "logs"
        return "unknown"

    def _set_active_tab_kind(self, tc: TabbedContent, panes: list[Any], target_kind: str) -> bool:
        for pane in panes:
            if self._pane_kind(pane) != target_kind:
                continue
            new_active = (
                getattr(pane, "id", None)
                or getattr(pane, "label", None)
                or getattr(pane, "title", None)
            )
            if new_active:
                tc.active = str(new_active)
                return True
        return False

    def _find_current_index(self, tc: TabbedContent, panes: list[Any]) -> int:
        active = tc.active
        active_s = str(active or "").lower()
        active_kind = "unknown"
        if "info" in active_s:
            active_kind = "info"
        elif "stats" in active_s:
            active_kind = "stats"
        elif "terminal" in active_s:
            active_kind = "terminal"
        elif "log" in active_s:
            active_kind = "logs"

        if active_kind != "unknown":
            for i, p in enumerate(panes):
                if self._pane_kind(p) == active_kind:
                    return i

        for i, p in enumerate(panes):
            pid = getattr(p, "id", None)
            label = getattr(p, "label", None) or getattr(p, "title", None)
            if isinstance(active, str):
                if pid == active or label == active:
                    return i
            else:
                if active is p:
                    return i
        return 0

    def action_switch_tab_prev(self) -> None:
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return
            cur_kind = self._active_tab_kind()
            if cur_kind == "logs":
                target_kind = "stats"
            elif cur_kind == "stats":
                target_kind = "info"
            elif cur_kind == "terminal":
                target_kind = "logs"
            elif cur_kind == "info":
                target_kind = "terminal"
            else:
                target_kind = "info"
            if not self._set_active_tab_kind(tc, panes, target_kind):
                cur_idx = self._find_current_index(tc, panes)
                prev_idx = cur_idx - 1 if cur_idx > 0 else len(panes) - 1
                pane = panes[prev_idx]
                new_active = getattr(pane, "id", None) or getattr(pane, "label", None) or getattr(pane, "title", None) or str(prev_idx)
                tc.active = str(new_active)
            if tc.active in ("info-tab", "Info"):
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))
            elif tc.active in ("stats-tab", "Stats"):
                self.call_after_refresh(self._focus_stats_tab)
            elif tc.active in ("terminal-tab", "Terminal"):
                self.call_after_refresh(lambda: self.set_focus(self.query_one("#container-terminal")))
        except Exception:
            self.app.bell()

    def action_switch_tab_next(self) -> None:
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return
            cur_kind = self._active_tab_kind()
            if cur_kind == "logs":
                target_kind = "terminal"
            elif cur_kind == "info":
                target_kind = "stats"
            elif cur_kind == "stats":
                target_kind = "logs"
            elif cur_kind == "terminal":
                target_kind = "info"
            else:
                target_kind = "terminal"
            if not self._set_active_tab_kind(tc, panes, target_kind):
                cur_idx = self._find_current_index(tc, panes)
                next_idx = cur_idx + 1 if cur_idx + 1 < len(panes) else 0
                pane = panes[next_idx]
                new_active = getattr(pane, "id", None) or getattr(pane, "label", None) or getattr(pane, "title", None) or str(next_idx)
                tc.active = str(new_active)
            if tc.active in ("info-tab", "Info"):
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))
            elif tc.active in ("stats-tab", "Stats"):
                self.call_after_refresh(self._focus_stats_tab)
            elif tc.active in ("terminal-tab", "Terminal"):
                self.call_after_refresh(lambda: self.set_focus(self.query_one("#container-terminal")))
        except Exception:
            self.app.bell()

    def action_switch_tab(self, tab: str) -> None:
        try:
            tc = self.query_one(TabbedContent)
            panes = list(tc.query(TabPane))
            if not panes:
                return
            if isinstance(tc.active, str) and tc.active == tab:
                return
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
                try:
                    tc.active = str(tab)
                except Exception:
                    self.app.bell()
                    return
            if tc.active in ("info-tab", "Info"):
                self.call_after_refresh(lambda: asyncio.create_task(self.load_container_info()))
            elif tc.active in ("stats-tab", "Stats"):
                self.call_after_refresh(self._focus_stats_tab)
            elif tc.active in ("terminal-tab", "Terminal"):
                self.call_after_refresh(lambda: self.set_focus(self.query_one("#container-terminal")))
        except Exception:
            self.app.bell()

    def colorize_log(self, line: str, highlight_span: Any = None) -> str:
        upper = line.upper()
        def _escape(s: str) -> str:
            return re.sub(r"([\[\]])", r"\\\1", s)
        spans: list[tuple[int,int,bool]] = []
        if isinstance(highlight_span, tuple):
            s, e = highlight_span
            spans = [(int(s), int(e), True)]
        elif isinstance(highlight_span, list):
            for item in highlight_span:
                if isinstance(item, tuple) and len(item) >= 2:
                    s = int(item[0])
                    e = int(item[1])
                    is_cur = bool(item[2]) if len(item) > 2 else False
                    spans.append((s, e, is_cur))
        if not spans:
            escaped_line = _escape(line)
            if "ERROR" in upper or "FATAL" in upper:
                return f"[red]{escaped_line}[/red]"
            elif "WARN" in upper:
                return f"[yellow]{escaped_line}[/yellow]"
            elif "INFO" in upper:
                return f"[green]{escaped_line}[/green]"
            elif "DEBUG" in upper:
                return f"[blue]{escaped_line}[/blue]"
            return escaped_line
        spans_sorted = sorted(spans, key=lambda x: x[0])
        merged: list[tuple[int,int,bool]] = []
        for s, e, is_cur in spans_sorted:
            s = max(0, s)
            e = max(s, e)
            if not merged:
                merged.append((s, e, is_cur))
                continue
            last_s, last_e, last_cur = merged[-1]
            if s <= last_e:
                merged[-1] = (last_s, max(last_e, e), last_cur or is_cur)
            else:
                merged.append((s, e, is_cur))
        out_parts: list[str] = []
        prev = 0
        for s, e, is_cur in merged:
            if s > prev:
                out_parts.append(_escape(line[prev:s]))
            seg = _escape(line[s:e])
            if is_cur:
                out_parts.append(f"[reverse][bold]{seg}[/bold][/reverse]")
            else:
                out_parts.append(f"[underline]{seg}[/underline]")
            prev = e
        if prev < len(line):
            out_parts.append(_escape(line[prev:]))
        highlighted = "".join(out_parts)
        if "ERROR" in upper or "FATAL" in upper:
            return f"[red]{highlighted}[/red]"
        elif "WARN" in upper:
            return f"[yellow]{highlighted}[/yellow]"
        elif "INFO" in upper:
            return f"[green]{highlighted}[/green]"
        elif "DEBUG" in upper:
            return f"[blue]{highlighted}[/blue]"
        return highlighted

    def focus_current_match(self) -> None:
        if self.current_match == -1 or not self.log_matches:
            return
        match = self.log_matches[self.current_match]
        line_idx = match["line_index"]
        try:
            scroll_view = self.query_one("#log-scroll", VerticalScroll)
            self.refresh_logs()
            try:
                virtual_height = max(1, scroll_view.virtual_size.height)
                view_height = max(1, scroll_view.size.height)
                total_lines = max(1, len(self.log_lines[-200:]))
                frac = line_idx / max(1, total_lines - 1)
                max_scroll = max(0, virtual_height - view_height)
                y = int(max_scroll * frac)
            except Exception:
                y = max(0, line_idx)
            scroll_view.scroll_to(0, y, animate=False)
            self.set_focus(scroll_view)
        except Exception:
            pass

    def action_next_match(self) -> None:
        if not self.log_matches:
            self.app.bell()
            return
        self.current_match = (self.current_match + 1) % len(self.log_matches) if self.current_match >= 0 else 0
        self.focus_current_match()

    def action_prev_match(self) -> None:
        if not self.log_matches:
            self.app.bell()
            return
        if self.current_match <= 0:
            self.current_match = len(self.log_matches) - 1
        else:
            self.current_match = (self.current_match - 1) % len(self.log_matches)
        self.focus_current_match()
<<<<<<< Updated upstream


=======
>>>>>>> Stashed changes
