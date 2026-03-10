from __future__ import annotations

from typing import Any

import requests_unixsocket
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static


DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()


class StatsTab(Container):
    """Live container performance metrics."""

    METRIC_ORDER = [
        "CPU usage:",
        "Memory usage:",
        "Network RX:",
        "Network TX:",
        "Block read:",
        "Block write:",
        "PIDs:",
        "Status:",
    ]

    def __init__(self, container_id: str) -> None:
        super().__init__(id="stats-tab-content")
        self.container_id = container_id
        self._refresh_timer = None
        self._refresh_in_flight = False
        self._value_widgets: dict[str, Static] = {}
        self._previous_cpu_total: int | None = None
        self._previous_system_total: int | None = None
        self._previous_online_cpus: int | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="stats-scroll"):
            yield Container(id="stats-container", classes="stats-content")

    def on_mount(self) -> None:
        self._build_rows()
        self._refresh_timer = self.set_interval(5.0, self.refresh_stats, pause=True)

    def on_unmount(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()

    def start_refresh(self) -> None:
        self.refresh_stats()
        if self._refresh_timer is not None:
            self._refresh_timer.resume()

    def stop_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.pause()

    def refresh_stats(self) -> None:
        if self._refresh_in_flight or not self.is_mounted:
            return
        self._refresh_in_flight = True
        self.run_worker(self._load_stats_worker, thread=True, group="stats-fetch", exclusive=True)

    def _load_stats_worker(self) -> None:
        try:
            payload = get_container_stats_payload(self.container_id)
            self.app.call_from_thread(self._apply_stats, payload)
        except Exception as exc:
            self.app.call_from_thread(self._apply_stats, {"error": f"Failed to fetch stats: {exc}"})

    def _apply_stats(self, payload: dict[str, Any]) -> None:
        self._refresh_in_flight = False
        if not self.is_mounted:
            return
        self._update_rows(self._format_stats(payload))

    def _build_rows(self) -> None:
        container = self.query_one("#stats-container", Container)
        lines: list[Horizontal] = []
        for index, label in enumerate(self.METRIC_ORDER):
            value_widget = Static("--", classes="stats-value", id=f"stats-value-{index}")
            self._value_widgets[label] = value_widget
            lines.append(
                Horizontal(
                    Static(str(label), classes="stats-label"),
                    value_widget,
                    classes="stats-line",
                )
            )

        if lines:
            container.mount(*lines)

        scroll = self.query_one("#stats-scroll", VerticalScroll)
        scroll.refresh(layout=True)

    def _update_rows(self, stats_data: dict[str, str]) -> None:
        for label in self.METRIC_ORDER:
            widget = self._value_widgets.get(label)
            if widget is None:
                continue
            value = stats_data.get(label, "--")
            widget.update(str(value))
            widget.classes = "stats-value"
            if "%" in str(value):
                widget.add_class("stats-highlight")
            if label in ("Status:", "Error:"):
                widget.add_class("stats-status")

    def _format_stats(self, payload: dict[str, Any]) -> dict[str, str]:
        error_message = str(payload.get("error") or "")
        if error_message:
            return {
                "CPU usage:": "--",
                "Memory usage:": "--",
                "Network RX:": "--",
                "Network TX:": "--",
                "Block read:": "--",
                "Block write:": "--",
                "PIDs:": "--",
                "Status:": error_message,
            }

        memory_stats = payload.get("memory_stats") or {}
        memory_usage = int(memory_stats.get("usage") or 0)
        memory_limit = int(memory_stats.get("limit") or 0)
        memory_percent = (memory_usage / memory_limit * 100) if memory_limit else 0.0

        cpu_stats = payload.get("cpu_stats") or {}
        cpu_usage = cpu_stats.get("cpu_usage") or {}
        current_cpu_total = int(cpu_usage.get("total_usage") or 0)
        current_system_total = int(cpu_stats.get("system_cpu_usage") or 0)
        online_cpus = int(cpu_stats.get("online_cpus") or 0) or len(cpu_usage.get("percpu_usage") or [])

        cpu_percent_text = self._format_cpu_percent(
            payload,
            current_cpu_total,
            current_system_total,
            online_cpus,
        )

        self._previous_cpu_total = current_cpu_total
        self._previous_system_total = current_system_total
        self._previous_online_cpus = online_cpus

        networks = payload.get("networks") or {}
        total_rx = 0
        total_tx = 0
        for values in networks.values():
            total_rx += int((values or {}).get("rx_bytes") or 0)
            total_tx += int((values or {}).get("tx_bytes") or 0)

        blkio_stats = payload.get("blkio_stats") or {}
        io_entries = blkio_stats.get("io_service_bytes_recursive") or []
        block_read = 0
        block_write = 0
        for entry in io_entries:
            op = str((entry or {}).get("op") or "").lower()
            value = int((entry or {}).get("value") or 0)
            if op == "read":
                block_read += value
            elif op == "write":
                block_write += value

        pids_current = int((payload.get("pids_stats") or {}).get("current") or 0)

        return {
            "CPU usage:": cpu_percent_text,
            "Memory usage:": f"{_bytes_to_human(memory_usage)} / {_bytes_to_human(memory_limit)} ({memory_percent:.2f}%)",
            "Network RX:": _bytes_to_human(total_rx),
            "Network TX:": _bytes_to_human(total_tx),
            "Block read:": _bytes_to_human(block_read),
            "Block write:": _bytes_to_human(block_write),
            "PIDs:": str(pids_current),
            "Status:": "live",
        }

    def _format_cpu_percent(
        self,
        payload: dict[str, Any],
        current_cpu_total: int,
        current_system_total: int,
        online_cpus: int,
    ) -> str:
        if (
            self._previous_cpu_total is not None
            and self._previous_system_total is not None
            and current_system_total > self._previous_system_total
            and current_cpu_total >= self._previous_cpu_total
            and online_cpus > 0
        ):
            cpu_delta = current_cpu_total - self._previous_cpu_total
            system_delta = current_system_total - self._previous_system_total
            if cpu_delta > 0 and system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                return f"{cpu_percent:.2f}%"

        precpu_stats = payload.get("precpu_stats") or {}
        precpu_usage = precpu_stats.get("cpu_usage") or {}
        previous_cpu_total = int(precpu_usage.get("total_usage") or 0)
        previous_system_total = int(precpu_stats.get("system_cpu_usage") or 0)
        fallback_online_cpus = online_cpus or self._previous_online_cpus or len(precpu_usage.get("percpu_usage") or [])
        if current_system_total > previous_system_total and current_cpu_total >= previous_cpu_total and fallback_online_cpus > 0:
            cpu_delta = current_cpu_total - previous_cpu_total
            system_delta = current_system_total - previous_system_total
            if cpu_delta > 0 and system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * fallback_online_cpus * 100.0
                return f"{cpu_percent:.2f}%"

        return "collecting..."

def get_container_stats_payload(container_id: str) -> dict[str, Any]:
    url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/stats"
    try:
        response = session.get(url, params={"stream": 0})
    except Exception as exc:
        return {"error": f"Failed to fetch stats: {exc}"}

    if response.status_code != 200:
        return {"error": f"Failed to fetch stats (HTTP {response.status_code})"}

    return response.json()


def _bytes_to_human(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.2f}{unit}"
        size /= 1024.0
    return f"{int(value)}B"
