from textual.binding import Binding

APP_BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("d", "toggle_dark", "Toggle dark mode"),
    Binding("j", "focus_next", "Next Container"),
    Binding("k", "focus_previous", "Previous Container"),
    Binding("s", "start_selected", "Start Container"),
    Binding("p", "stop_selected", "Stop Container"),
    Binding("e", "exec_selected", "Exec Shell"),
    Binding("l", "logs_selected", "View Logs"),
]
