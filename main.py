from textual.app import App, ComposeResult
from textual.widgets import Footer, Static
from textual.containers import Vertical
from bindings import APP_BINDINGS
from service import delete_container, get_containers, start_container, stop_container
from typing import Dict
from container_shell import run_exec_shell
from container_action_menu import ContainerActionScreen


class ContainerCard(Static):
    def __init__(self, idx: int, container_id: str, name: str, image: str, status: str):
        super().__init__(classes="container-card")
        self.idx = idx 
        self.container_id = container_id
        self.container_name = name
        self.image = image
        self.status = status
        self.status_widget: Static | None = None

    can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(f"[b]{self.idx}. {self.container_name}[/b]", classes="col name")
        yield Static(self.image, classes="col image")
        self.status_widget = Static(self.status, classes="col status")
        yield self.status_widget

    def update_status(self, new_status: str):
        if self.status != new_status:
            self.status = new_status
            if self.status_widget:
                self.status_widget.update(new_status)


class DockerManager(App):
    CSS_PATH = "ui.tcss"
    BINDINGS = APP_BINDINGS  # pyright: ignore
    ENABLE_COMMAND_PALETTE = False

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, ContainerCard] = {}

    def compose(self) -> ComposeResult:
        yield Static("🛠 Docker Manager", classes="header-title")

        self.container_list = Vertical(id="container-list")
        yield self.container_list

        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self.action_run_ls)
        self.action_run_ls()

    def action_refresh(self):
        self.action_run_ls()

    def action_run_ls(self):
        containers = get_containers()
        seen_ids = set()

        for idx, container_id, name, image, status in containers:
            seen_ids.add(container_id)

            if container_id in self.cards:
                card = self.cards[container_id]
                card.update_status(status)
            else:
                card = ContainerCard(idx,container_id, name, image, status)
                self.cards[container_id] = card
                self.container_list.mount(card)
        
        for container_id in list(self.cards.keys()):
            if container_id not in seen_ids:
                card = self.cards.pop(container_id)
                card.remove()

    def action_focus_next(self):
        self.screen.focus_next()
        self.query_one("#container-list").scroll_visible()

    def action_focus_previous(self):
        self.screen.focus_previous()
        self.query_one("#container-list").scroll_visible()

    def action_start_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            success = start_container(focused.container_id)
            if success:
                self.action_run_ls()

    def action_stop_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            success = stop_container(focused.container_id)
            if success:
                self.action_run_ls()

    def action_delete_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            success = delete_container(focused.container_id)
            if success:
                self.action_run_ls()
                
    def action_exec_selected(self) -> None:
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            run_exec_shell(focused.container_id)

    def action_open_menu(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            self.push_screen(ContainerActionScreen(focused.container_id, focused.container_name))

    def on_container_action_screen_selected(
        self, message: ContainerActionScreen.Selected
    ):
        cid = message.container_id
        action = message.action

        if action == "start":
            start_container(cid)
        elif action == "stop":
            stop_container(cid)
        elif action == "delete":
            delete_container(cid)
        elif action == "logs":
            self.push_screen(ContainerActionScreen(cid, ''))
        elif action == "exec":
            run_exec_shell(cid)

        self.action_run_ls()


if __name__ == "__main__":
    DockerManager().run()
