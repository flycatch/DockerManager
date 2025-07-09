from textual.binding import Binding

APP_BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("j", "focus_next", "Next Container"),
    Binding("k", "focus_previous", "Previous Container"),
    Binding("enter", "open_menu", "Container Actions"),
]
