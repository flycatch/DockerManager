from textual.app import ComposeResult
from textual.widgets import Static


class ImageCard(Static):
    can_focus = True

    def __init__(self, idx: int, image_id: str, reference: str, size: str, created: str, containers: str) -> None:
        super().__init__(classes="image-card")
        self.idx = idx
        self.image_id = image_id
        self.reference = reference
        self.image_size = size
        self.created_at = created
        self.container_count = containers
        self._reference_widget: Static | None = None
        self._id_widget: Static | None = None
        self._size_widget: Static | None = None
        self._created_widget: Static | None = None
        self._containers_widget: Static | None = None

    def compose(self) -> ComposeResult:
        self._reference_widget = Static(f"[b]{self.reference}[/b]", classes="image-col reference")
        yield self._reference_widget
        self._id_widget = Static(self.image_id.split(":")[-1][:12], classes="image-col image-id")
        yield self._id_widget
        self._size_widget = Static(self.image_size, classes="image-col size")
        yield self._size_widget
        self._created_widget = Static(self.created_at, classes="image-col created")
        yield self._created_widget
        self._containers_widget = Static(self.container_count, classes="image-col containers")
        yield self._containers_widget

    def update_details(self, reference: str, size: str, created: str, containers: str) -> None:
        self.reference = reference
        self.image_size = size
        self.created_at = created
        self.container_count = containers
        if self._reference_widget is not None:
            self._reference_widget.update(f"[b]{self.reference}[/b]")
        if self._size_widget is not None:
            self._size_widget.update(self.image_size)
        if self._created_widget is not None:
            self._created_widget.update(self.created_at)
        if self._containers_widget is not None:
            self._containers_widget.update(self.container_count)
