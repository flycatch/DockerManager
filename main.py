from textual.app import App, ComposeResult
from textual.widgets import Footer, Static, Tree, TabPane, TabbedContent
from textual.containers import Vertical, Horizontal
from textual.reactive import var
from textual.message import Message
from textual.widgets._tree import TreeNode, NodeID
from rich.text import Text
from bindings import APP_BINDINGS
from service import delete_container, get_projects_with_containers, start_container, stop_container
from typing import Dict, Any
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
    BINDINGS = APP_BINDINGS
    ENABLE_COMMAND_PALETTE = False

    def __init__(self):
        super().__init__()
        self.cards: Dict[str, ContainerCard] = {}
        self.uncategorized_cards: Dict[str, ContainerCard] = {}
        self.projects: dict[str, list[tuple[int, str, str, str, str]]] = {}
        self._refreshing = False
        self.current_project: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("🛠 Docker Manager", classes="header-title")

        with TabbedContent():
            with TabPane("🧊 All Containers", id="tab-uncategorized"):
                self.uncategorized_list = Vertical(id="uncategorized-list")
                yield self.uncategorized_list

            with TabPane("🧩 Compose Projects", id="tab-projects"):
                self.project_tree = Tree("Compose Projects", id="project-tree")
                self.container_list = Vertical(id="container-list")
                yield Horizontal(self.project_tree, self.container_list)

        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(2.0, self.trigger_background_refresh)
        await self.refresh_projects()

    def trigger_background_refresh(self) -> None:
        self.run_worker(self.refresh_projects, exclusive=True, group="refresh")

    async def refresh_projects(self):
        if self._refreshing:
            return
        self._refreshing = True

        try:
            all_projects = get_projects_with_containers()

            # Update Uncategorized View
            if "Uncategorized" in all_projects:
                await self.sync_card_list(
                    all_projects["Uncategorized"],
                    self.uncategorized_cards,
                    self.uncategorized_list
                )

            # Update Compose Project Tree
            self.project_tree.root.remove_children()
            for project, containers in all_projects.items():
                if project != "Uncategorized":
                    self.project_tree.root.add(project, data=containers)

            self.project_tree.root.expand()

            # Update currently selected project containers
            if self.current_project and self.project_tree.root.children:
                selected_node = next(
                    (child for child in self.project_tree.root.children if str(child.label.plain if isinstance(child.label, Text) else child.label) == self.current_project),
                    None
                )
                if selected_node:
                    await self.refresh_container_list(selected_node.data or [])

        finally:
            self._refreshing = False

    async def refresh_container_list(self, containers: list[tuple[int, str, str, str, str]]):
        await self.sync_card_list(containers, self.cards, self.container_list)

    async def sync_card_list(
        self,
        container_data: list[tuple[int, str, str, str, str]],
        container_map: dict[str, ContainerCard],
        mount_target: Vertical
    ):
        new_ids = {cid for _, cid, *_ in container_data}
        old_ids = set(container_map.keys())

        # Remove cards that no longer exist
        for cid in old_ids - new_ids:
            card = container_map.pop(cid)
            await card.remove()

        # Add or update cards
        for idx, cid, name, image, status in container_data:
            if cid in container_map:
                container_map[cid].update_status(status)
            else:
                card = ContainerCard(idx, cid, name, image, status)
                container_map[cid] = card
                await mount_target.mount(card)

    async def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        containers: Any = event.node.data
        if containers:
            await self.refresh_container_list(containers)

        label = event.node.label
        if isinstance(label, Text):
            self.current_project = label.plain
        else:
            self.current_project = str(label)

    def action_focus_next(self):
        self.screen.focus_next()
        self.query_one("#container-list").scroll_visible()

    def action_focus_previous(self):
        self.screen.focus_previous()
        self.query_one("#container-list").scroll_visible()

    def action_start_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            if start_container(focused.container_id):
                self.call_from_thread(self.refresh_projects)

    def action_stop_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            if stop_container(focused.container_id):
                self.call_from_thread(self.refresh_projects)

    def action_delete_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            if delete_container(focused.container_id):
                self.call_from_thread(self.refresh_projects)

    def action_exec_selected(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            run_exec_shell(focused.container_id)

    def action_open_menu(self):
        focused = self.screen.focused
        if isinstance(focused, ContainerCard):
            self.push_screen(ContainerActionScreen(focused.container_id, focused.container_name))

    def on_container_action_screen_selected(self, message: ContainerActionScreen.Selected):
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

        self.call_from_thread(self.refresh_projects)


if __name__ == "__main__":
    DockerManager().run()
