from textual.binding import Binding, BindingType
from typing import cast

APP_BINDINGS = cast(list[BindingType], [
    Binding("q", "quit", "Quit"),
    Binding("k", "focus_next", "Next Container"),
    Binding("j", "focus_previous", "Previous Container"),
    Binding("enter", "open_menu", "Container Actions"),
    Binding("u", "start_project", "Project Up/Start"),
    Binding("o", "stop_project", "Project Down/Stop"),
    Binding("r", "restart_project", "Restart Project"),
    Binding("x", "delete_project", "Delete Project"),
    
])
