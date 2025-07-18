from textual.binding import Binding, BindingType
from typing import cast

APP_BINDINGS = cast(list[BindingType], [
    Binding("q", "quit", "Quit"),
    Binding("k", "focus_next", "Next Container"),
    Binding("j", "focus_previous", "Previous Container"),
    Binding("enter", "open_menu", "Container Actions")
])
