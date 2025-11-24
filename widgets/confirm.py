from textual.screen import ModalScreen
from textual.widgets import Static, Input, Footer
from textual.binding import Binding
from typing import Callable

class ConfirmActionScreen(ModalScreen):
    BINDINGS = [
        Binding("y", "confirm_yes", "Yes", show=True, key_display="y/Y"),
        Binding("Y", "confirm_yes", "Yes", show=False),
        Binding("n", "confirm_no", "No", show=True, key_display="n/N"),
        Binding("N", "confirm_no", "No", show=False),
        Binding("escape", "confirm_no", "Cancel", show=False),
    ]

    def __init__(self, message: str, callback: Callable[[bool], None]):
        super().__init__()
        self.message = message
        self.callback = callback

    def compose(self):
        from textual.containers import Container
        # Centered overlay container
        yield Container(
            Static(self.message, classes="confirm-message"),
            id="confirm-overlay",
            classes="confirm-overlay"
        )
        yield Footer()

    def action_confirm_yes(self):
        self.dismiss(True)

    def action_confirm_no(self):
        self.dismiss(False)

    def dismiss(self, result=None):
        # Call the base class dismiss and return its result
        ret = super().dismiss(result)
        if self.callback:
            self.callback(bool(result))
        return ret
