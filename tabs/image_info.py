from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static

from service import get_image_info_dict


class ImageInfoTab(Container):
    def __init__(self, image_ref: str) -> None:
        super().__init__(id="image-info-tab")
        self.image_ref = image_ref
        self._load_in_flight = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="image-info-scroll"):
            yield Container(id="image-info-container", classes="info-content")

    def on_mount(self) -> None:
        self.call_later(self.load_info)

    def load_info(self) -> None:
        if self._load_in_flight or not self.is_mounted:
            return
        self._load_in_flight = True
        self.run_worker(self._load_worker, thread=True, group="image-info", exclusive=True)

    def _load_worker(self) -> None:
        info = get_image_info_dict(self.image_ref)
        self.app.call_from_thread(self._apply_info, info)

    def _apply_info(self, info: dict[str, str]) -> None:
        self._load_in_flight = False
        if not self.is_mounted:
            return
        container = self.query_one("#image-info-container", Container)
        container.remove_children()
        lines: list[Horizontal] = []
        for label, value in info.items():
            lines.append(
                Horizontal(
                    Static(str(label), classes="label"),
                    Static(str(value), classes="value"),
                    classes="info-line",
                )
            )
        if lines:
            container.mount(*lines)
        self.query_one("#image-info-scroll", VerticalScroll).refresh(layout=True)
