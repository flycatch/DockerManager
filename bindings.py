from textual.binding import Binding

APP_BINDINGS = [
    Binding("q", "quit", "Quit"),
    Binding("k", "focus_next", "Next Container"),
    Binding("j", "focus_previous", "Previous Container"),
    Binding("enter", "open_menu", "Container Actions")
]
