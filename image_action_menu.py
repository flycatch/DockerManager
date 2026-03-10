from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Footer, TabbedContent, TabPane

from tabs.image_filesystem import ImageFilesystemTab
from tabs.image_info import ImageInfoTab


class ImageActionScreen(ModalScreen):
    CSS_PATH = "tcss/image_browser.tcss"
    BINDINGS: list[BindingType] = [
        Binding("escape", "close_screen", "Close", key_display="ESC"),
    ]

    def __init__(self, image_id: str, image_ref: str) -> None:
        super().__init__()
        self.image_id = image_id
        self.image_ref = image_ref
        self.fs_tab: ImageFilesystemTab | None = None

    def compose(self):
        with TabbedContent():
            with TabPane("Info", id="image-info-pane"):
                yield ImageInfoTab(self.image_id)
            with TabPane("Filesystem", id="image-filesystem-pane"):
                self.fs_tab = ImageFilesystemTab(self.image_ref)
                yield self.fs_tab
        yield Footer()

    def action_close_screen(self) -> None:
        self.dismiss()

    def on_unmount(self) -> None:
        if self.fs_tab is not None:
            self.fs_tab.cleanup()

    def action_switch_tab_next(self) -> None:
        self._switch_tab(1)

    def action_switch_tab_prev(self) -> None:
        self._switch_tab(-1)

    def _switch_tab(self, step: int) -> None:
        tc = self.query_one(TabbedContent)
        panes = [pane for pane in tc.query(TabPane) if pane.id]
        ids = [pane.id for pane in panes if pane.id]
        if not ids:
            return
        try:
            idx = ids.index(tc.active)
        except ValueError:
            idx = 0
        next_id = ids[(idx + step) % len(ids)]
        if next_id != "image-filesystem-pane" and self.fs_tab is not None:
            self.fs_tab.deactivate()
        tc.active = next_id
        self.call_after_refresh(lambda: self._focus_active_tab(next_id))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "image-filesystem-pane" and self.fs_tab is not None:
            self.fs_tab.start(focus_tree=True)
        elif self.fs_tab is not None:
            self.fs_tab.deactivate()
            self.call_after_refresh(lambda: self._focus_active_tab(event.pane.id))

    def on_key(self, event) -> None:
        if event.key == "shift+left":
            self.action_switch_tab_prev()
            event.stop()
            return
        if event.key == "shift+right":
            self.action_switch_tab_next()
            event.stop()

    def _focus_active_tab(self, pane_id: str) -> None:
        if pane_id == "image-info-pane":
            try:
                self.app.set_focus(self.query_one("#image-info-scroll"))
            except Exception:
                pass
        elif pane_id == "image-filesystem-pane" and self.fs_tab is not None:
            try:
                self.fs_tab._focus_tree()
            except Exception:
                pass
