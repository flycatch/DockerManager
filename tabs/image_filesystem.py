from __future__ import annotations

from textual.containers import Horizontal, VerticalScroll
from textual.app import ComposeResult
from textual.events import Key
from textual.widgets import Static, TabbedContent, Tree

from service import (
    create_temp_container_for_image,
    list_container_filesystem,
    read_container_file_preview,
    remove_container,
    remove_image_temp_containers,
)
from widgets.loading_screen import LoadingOverlay


class ImageFilesystemTab(Horizontal):
    def __init__(self, image_ref: str) -> None:
        super().__init__(id="image-filesystem-tab")
        self.image_ref = image_ref
        self.temp_container_id: str | None = None
        self.initialized = False
        self._loading_paths: set[str] = set()
        self._focus_tree_when_ready = False
        self._loading_overlay: LoadingOverlay | None = None
        self._closing = False

    def compose(self) -> ComposeResult:
        tree = Tree("/", id="image-filesystem-tree")
        tree.root.data = {"path": "/", "kind": "dir", "loaded": False}
        tree.root.allow_expand = True
        yield tree
        with VerticalScroll(id="image-filesystem-preview-scroll"):
            yield Static("Select a directory or file.", id="image-filesystem-preview")

    def start(self, *, focus_tree: bool = True) -> None:
        if focus_tree:
            self._focus_tree_when_ready = True
        if self.initialized:
            if self.temp_container_id and focus_tree:
                self._focus_tree()
            return
        self.initialized = True
        self._show_loading("creating te,porary container")
        self.app.notify("creating temporary container", severity="information", timeout=2)
        self.run_worker(self._initialize_worker, thread=True, group="image-fs-init", exclusive=True)

    def on_unmount(self) -> None:
        self._hide_loading()

    def cleanup(self) -> None:
        self._closing = True
        temp_id = self.temp_container_id
        self.temp_container_id = None
        if temp_id:
            self.run_worker(lambda: remove_container(temp_id), thread=True, group="image-fs-cleanup", exclusive=True)
        self.run_worker(
            lambda: remove_image_temp_containers(self.image_ref),
            thread=True,
            group="image-fs-cleanup-by-label",
            exclusive=True,
        )

    def _initialize_worker(self) -> None:
        self.app.call_from_thread(self._update_loading, "creating te,porary container")
        temp_container_id = create_temp_container_for_image(self.image_ref)
        if not temp_container_id:
            self.app.call_from_thread(self._apply_init_error, "Failed to create or start temp container.")
            return
        self.app.call_from_thread(self._remember_temp_container_id, temp_container_id)
        self.app.call_from_thread(self._update_loading, "Loading filesystem...")
        kind, entries, error = list_container_filesystem(temp_container_id, "/")
        self.app.call_from_thread(self._apply_root, temp_container_id, kind, entries, error)

    def _remember_temp_container_id(self, temp_container_id: str) -> None:
        self.temp_container_id = temp_container_id
        if self._closing and temp_container_id:
            temp_id = temp_container_id
            self.temp_container_id = None
            self.run_worker(lambda: remove_container(temp_id), thread=True, group="image-fs-cleanup", exclusive=True)

    def _apply_root(self, temp_container_id: str, kind: str, entries: list[dict[str, object]], error: str | None) -> None:
        if self._closing or not self.is_mounted:
            remove_container(temp_container_id)
            return
        self.temp_container_id = temp_container_id
        if error:
            self._hide_loading()
            self._set_preview(error)
            return
        tree = self.query_one("#image-filesystem-tree", Tree)
        tree.root.remove_children()
        tree.root.data = {"path": "/", "kind": kind, "loaded": True}
        self._populate_node(tree.root, entries)
        tree.root.expand()
        self._hide_loading()
        self._set_preview("Filesystem ready. Select a file to preview it.")
        if self._focus_tree_when_ready and self._is_filesystem_active():
            self._focus_tree()
        self._focus_tree_when_ready = False

    def _apply_init_error(self, message: str) -> None:
        self._hide_loading()
        self._set_preview(message)

    def _populate_node(self, node, entries: list[dict[str, object]]) -> None:
        for entry in entries:
            name = str(entry["name"])
            is_dir = bool(entry["is_dir"])
            label = f"{name}/" if is_dir else name
            child = node.add(
                label,
                data={
                    "path": str(entry["path"]),
                    "kind": "dir" if is_dir else "file",
                    "loaded": False,
                },
            )
            child.allow_expand = is_dir

    def _set_preview(self, text: str) -> None:
        self.query_one("#image-filesystem-preview", Static).update(text)

    def _show_loading(self, message: str) -> None:
        if self._loading_overlay is None:
            self._loading_overlay = LoadingOverlay(message)
            self.app.screen.mount(self._loading_overlay)
            self._loading_overlay.refresh(layout=True)
            self.app.refresh()
        else:
            self._loading_overlay.update_message(message)
            self._loading_overlay.refresh(layout=True)
            self.app.refresh()

    def _update_loading(self, message: str) -> None:
        if self._loading_overlay is None:
            self._show_loading(message)
            return
        self._loading_overlay.update_message(message)
        self._loading_overlay.refresh(layout=True)
        self.app.refresh()

    def _hide_loading(self) -> None:
        overlay = self._loading_overlay
        self._loading_overlay = None
        if overlay is not None:
            self.app.run_worker(overlay.remove_self())

    def _focus_tree(self) -> None:
        self.app.set_focus(self.query_one("#image-filesystem-tree", Tree))

    def _focus_preview(self) -> None:
        self.app.set_focus(self.query_one("#image-filesystem-preview-scroll", VerticalScroll))

    def deactivate(self) -> None:
        self._focus_tree_when_ready = False

    def _is_filesystem_active(self) -> bool:
        try:
            return self.screen.query_one(TabbedContent).active == "image-filesystem-pane"
        except Exception:
            return False

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            focused = self.app.screen.focused
            tree = self.query_one("#image-filesystem-tree", Tree)
            if focused is tree:
                node = tree.cursor_node or tree.root
                if node is not None:
                    data = node.data or {}
                    path = str(data.get("path") or "/")
                    kind = str(data.get("kind") or "dir")
                    if kind == "dir":
                        self._load_directory(node, path)
                        event.stop()
                        return
                    self._load_file_preview(path)
                    event.stop()
                    return
        if event.key == "left":
            focused = self.app.screen.focused
            tree = self.query_one("#image-filesystem-tree", Tree)
            if focused is tree:
                node = tree.cursor_node or tree.root
                if node is not None and node.is_expanded:
                    node.collapse()
                    event.stop()
                    return
        if event.key != "escape":
            return
        focused = self.app.screen.focused
        preview_scroll = self.query_one("#image-filesystem-preview-scroll", VerticalScroll)
        if focused is preview_scroll:
            self._focus_tree()
            event.stop()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data or {}
        path = str(data.get("path") or "/")
        kind = str(data.get("kind") or "dir")
        if kind == "dir":
            self._load_directory(event.node, path)
            return
        self._load_file_preview(path)

    def _load_directory(self, node, path: str) -> None:
        if self.temp_container_id is None or path in self._loading_paths:
            return
        data = node.data or {}
        if data.get("loaded"):
            node.expand() if not node.is_expanded else node.collapse()
            return
        self._loading_paths.add(path)
        self._set_preview(f"Loading {path} ...")
        self.run_worker(
            lambda: self._directory_worker(node, path),
            thread=True,
            group=f"image-fs-dir-{path}",
        )

    def _directory_worker(self, node, path: str) -> None:
        kind, entries, error = list_container_filesystem(self.temp_container_id or "", path)
        self.app.call_from_thread(self._apply_directory, node, path, kind, entries, error)

    def _apply_directory(self, node, path: str, kind: str, entries: list[dict[str, object]], error: str | None) -> None:
        self._loading_paths.discard(path)
        if error:
            self._set_preview(error)
            return
        node.remove_children()
        node.data = {"path": path, "kind": kind, "loaded": True}
        self._populate_node(node, entries)
        node.expand()
        self._set_preview(path)
        if self._is_filesystem_active():
            self._focus_tree()

    def _load_file_preview(self, path: str) -> None:
        if self.temp_container_id is None:
            return
        self._show_loading(f"Opening {path} ...")
        self.run_worker(
            lambda: self._preview_worker(path),
            thread=True,
            group=f"image-fs-file-{path}",
            exclusive=True,
        )

    def _preview_worker(self, path: str) -> None:
        preview = read_container_file_preview(self.temp_container_id or "", path)
        self.app.call_from_thread(self._apply_preview, preview)

    def _apply_preview(self, preview: str) -> None:
        self._hide_loading()
        self._set_preview(preview)
        preview_scroll = self.query_one("#image-filesystem-preview-scroll", VerticalScroll)
        preview_scroll.scroll_home(animate=False)
        if self._is_filesystem_active():
            self._focus_preview()
