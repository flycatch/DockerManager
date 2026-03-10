from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests_unixsocket
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static


DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock"
session = requests_unixsocket.Session()


class StatsTab(Container):
    """Live container performance metrics and charts."""

    SUMMARY_ORDER = [
        "CPU usage:",
        "Memory usage:",
        "Network RX:",
        "Network TX:",
        "Block read:",
        "Block write:",
        "PIDs:",
        "Status:",
    ]

    CHART_TITLES = {
        "cpu": "CPU",
        "memory": "Memory",
        "network": "Network I/O",
        "disk": "Disk I/O",
        "processes": "Processes",
        "state": "Container State",
        "uptime": "Uptime",
        "health": "Health",
        "ports": "Ports",
        "mounts": "Mounts",
    }

    def __init__(self, container_id: str) -> None:
        super().__init__(id="stats-tab-content")
        self.container_id = container_id
        self._refresh_timer = None
        self._refresh_in_flight = False
        self._value_widgets: dict[str, Static] = {}
        self._chart_widgets: dict[str, Static] = {}
        self._previous_cpu_total: int | None = None
        self._previous_system_total: int | None = None
        self._previous_online_cpus: int | None = None
        self._previous_network_rx: int | None = None
        self._previous_network_tx: int | None = None
        self._previous_disk_read: int | None = None
        self._previous_disk_write: int | None = None
        self._cpu_history: list[float] = []
        self._memory_history: list[float] = []
        self._network_rx_history: list[float] = []
        self._network_tx_history: list[float] = []
        self._disk_read_history: list[float] = []
        self._disk_write_history: list[float] = []

    def compose(self) -> ComposeResult:
        with Container(id="stats-layout"):
            with Container(id="stats-summary"):
                for label in self.SUMMARY_ORDER:
                    value_widget = Static("--", classes="stats-value")
                    self._value_widgets[label] = value_widget
                    with Horizontal(classes="stats-line"):
                        yield Static(label, classes="stats-label")
                        yield value_widget
            with Container(id="stats-chart-grid"):
                for key, title in self.CHART_TITLES.items():
                    with Container(classes="stats-chart-card"):
                        yield Static(title, classes="stats-chart-title")
                        chart_widget = Static("", classes="stats-chart")
                        self._chart_widgets[key] = chart_widget
                        yield chart_widget

    def on_mount(self) -> None:
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
        summary, chart_data = self._format_stats(payload)
        self._update_summary(summary)
        self._update_charts(chart_data)

    def _update_summary(self, summary: dict[str, str]) -> None:
        for label in self.SUMMARY_ORDER:
            widget = self._value_widgets.get(label)
            if widget is None:
                continue
            value = summary.get(label, "--")
            widget.update(str(value))
            widget.classes = "stats-value"
            if "%" in str(value):
                widget.add_class("stats-highlight")
            if label == "Status:":
                widget.add_class("stats-status")

    def _update_charts(self, chart_data: dict[str, dict[str, Any]]) -> None:
        for key, widget in self._chart_widgets.items():
            payload = chart_data.get(key, {})
            widget.update(_render_metric_card(payload))

    def _format_stats(self, payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        error_message = str(payload.get("error") or "")
        started_at = str(payload.get("started_at") or "")
        health_status = str(payload.get("health_status") or "unknown")
        port_mappings = payload.get("port_mappings") or []
        mount_mappings = payload.get("mount_mappings") or []
        if error_message:
            summary = {
                "CPU usage:": "--",
                "Memory usage:": "--",
                "Network RX:": "--",
                "Network TX:": "--",
                "Block read:": "--",
                "Block write:": "--",
                "PIDs:": "--",
                "Status:": str(payload.get("state_status") or error_message),
            }
            return summary, self._current_chart_payload()

        state_status = str(payload.get("state_status") or "unknown")
        if state_status != "running":
            pids_current = int((payload.get("pids_stats") or {}).get("current") or 0)
            self._previous_cpu_total = None
            self._previous_system_total = None
            self._previous_online_cpus = None
            self._previous_network_rx = None
            self._previous_network_tx = None
            self._previous_disk_read = None
            self._previous_disk_write = None
            self._network_rx_history = _push_history(self._network_rx_history, 0.0)
            self._network_tx_history = _push_history(self._network_tx_history, 0.0)
            self._disk_read_history = _push_history(self._disk_read_history, 0.0)
            self._disk_write_history = _push_history(self._disk_write_history, 0.0)
            summary = {
                "CPU usage:": "--",
                "Memory usage:": "--",
                "Network RX:": "--",
                "Network TX:": "--",
                "Block read:": "--",
                "Block write:": "--",
                "PIDs:": str(pids_current),
                "Status:": state_status,
            }
            chart_payload = self._current_chart_payload()
            chart_payload["network"]["subtitle"] = "No recent traffic"
            chart_payload["disk"]["subtitle"] = "No recent disk activity"
            chart_payload["processes"] = _build_process_payload(pids_current)
            chart_payload["state"] = _build_state_payload(state_status)
            chart_payload["uptime"] = _build_uptime_payload(started_at, state_status)
            chart_payload["health"] = _build_health_payload(health_status)
            chart_payload["ports"] = _build_mapping_payload(
                port_mappings,
                "No published or exposed ports",
            )
            chart_payload["mounts"] = _build_mapping_payload(
                mount_mappings,
                "No mounted volumes or binds",
            )
            return summary, chart_payload

        memory_stats = payload.get("memory_stats") or {}
        memory_usage = int(memory_stats.get("usage") or 0)
        memory_limit = int(memory_stats.get("limit") or 0)
        memory_percent = (memory_usage / memory_limit * 100) if memory_limit else 0.0

        cpu_stats = payload.get("cpu_stats") or {}
        cpu_usage = cpu_stats.get("cpu_usage") or {}
        current_cpu_total = int(cpu_usage.get("total_usage") or 0)
        current_system_total = int(cpu_stats.get("system_cpu_usage") or 0)
        online_cpus = int(cpu_stats.get("online_cpus") or 0) or len(cpu_usage.get("percpu_usage") or [])
        cpu_percent_text = self._format_cpu_percent(payload, current_cpu_total, current_system_total, online_cpus)
        cpu_percent_value = _parse_percent(cpu_percent_text)

        self._previous_cpu_total = current_cpu_total
        self._previous_system_total = current_system_total
        self._previous_online_cpus = online_cpus
        if cpu_percent_value is not None:
            self._cpu_history = _push_history(self._cpu_history, cpu_percent_value)
        self._memory_history = _push_history(self._memory_history, memory_percent)

        networks = payload.get("networks") or {}
        total_rx = 0
        total_tx = 0
        for values in networks.values():
            total_rx += int((values or {}).get("rx_bytes") or 0)
            total_tx += int((values or {}).get("tx_bytes") or 0)
        rx_rate = 0.0
        tx_rate = 0.0
        if self._previous_network_rx is not None and total_rx >= self._previous_network_rx:
            rx_rate = (total_rx - self._previous_network_rx) / 5.0
        if self._previous_network_tx is not None and total_tx >= self._previous_network_tx:
            tx_rate = (total_tx - self._previous_network_tx) / 5.0
        self._previous_network_rx = total_rx
        self._previous_network_tx = total_tx
        self._network_rx_history = _push_history(self._network_rx_history, rx_rate)
        self._network_tx_history = _push_history(self._network_tx_history, tx_rate)

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
        read_rate = 0.0
        write_rate = 0.0
        if self._previous_disk_read is not None and block_read >= self._previous_disk_read:
            read_rate = (block_read - self._previous_disk_read) / 5.0
        if self._previous_disk_write is not None and block_write >= self._previous_disk_write:
            write_rate = (block_write - self._previous_disk_write) / 5.0
        self._previous_disk_read = block_read
        self._previous_disk_write = block_write
        self._disk_read_history = _push_history(self._disk_read_history, read_rate)
        self._disk_write_history = _push_history(self._disk_write_history, write_rate)

        pids_current = int((payload.get("pids_stats") or {}).get("current") or 0)
        summary = {
            "CPU usage:": cpu_percent_text,
            "Memory usage:": f"{_bytes_to_human(memory_usage)} / {_bytes_to_human(memory_limit)} ({memory_percent:.2f}%)",
            "Network RX:": _bytes_to_human(total_rx),
            "Network TX:": _bytes_to_human(total_tx),
            "Block read:": _bytes_to_human(block_read),
            "Block write:": _bytes_to_human(block_write),
            "PIDs:": str(pids_current),
            "Status:": state_status,
        }
        chart_payload = self._current_chart_payload()
        chart_payload["cpu"]["subtitle"] = f"Avg {_format_chart_value(chart_payload['cpu']['avg'], '%')}   Peak {_format_chart_value(chart_payload['cpu']['max'], '%')}"
        chart_payload["memory"]["subtitle"] = f"{_bytes_to_human(memory_usage)} used of {_bytes_to_human(memory_limit)}"
        chart_payload["network"]["sections"] = [
            _build_split_metric("RX", self._network_rx_history, "/s", total_rx),
            _build_split_metric("TX", self._network_tx_history, "/s", total_tx),
        ]
        chart_payload["disk"]["sections"] = [
            _build_split_metric("READ", self._disk_read_history, "/s", block_read),
            _build_split_metric("WRITE", self._disk_write_history, "/s", block_write),
        ]
        chart_payload["processes"] = _build_process_payload(pids_current)
        chart_payload["state"] = _build_state_payload(state_status)
        chart_payload["uptime"] = _build_uptime_payload(started_at, state_status)
        chart_payload["health"] = _build_health_payload(health_status)
        chart_payload["ports"] = _build_mapping_payload(
            port_mappings,
            "No published or exposed ports",
        )
        chart_payload["mounts"] = _build_mapping_payload(
            mount_mappings,
            "No mounted volumes or binds",
        )
        return summary, chart_payload

    def _current_chart_payload(self) -> dict[str, dict[str, Any]]:
        cpu_current = self._cpu_history[-1] if self._cpu_history else 0.0
        mem_current = self._memory_history[-1] if self._memory_history else 0.0
        return {
            "cpu": {
                "value": cpu_current,
                "display": f"{cpu_current:.2f}%" if self._cpu_history else "--",
                "avg": _history_avg(self._cpu_history),
                "max": max(self._cpu_history) if self._cpu_history else 0.0,
                "unit": "%",
                "scale_max": max(100.0, max(self._cpu_history) if self._cpu_history else 0.0),
                "subtitle": "Recent processor load",
            },
            "memory": {
                "value": mem_current,
                "display": f"{mem_current:.2f}%" if self._memory_history else "--",
                "avg": _history_avg(self._memory_history),
                "max": max(self._memory_history) if self._memory_history else 0.0,
                "unit": "%",
                "scale_max": 100.0,
                "subtitle": "Working set usage",
            },
            "network": {
                "sections": [
                    _build_split_metric("RX", self._network_rx_history, "/s", 0),
                    _build_split_metric("TX", self._network_tx_history, "/s", 0),
                ],
            },
            "disk": {
                "sections": [
                    _build_split_metric("READ", self._disk_read_history, "/s", 0),
                    _build_split_metric("WRITE", self._disk_write_history, "/s", 0),
                ],
            },
            "processes": _build_process_payload(0),
            "state": _build_state_payload("unknown"),
            "uptime": _build_uptime_payload("", "unknown"),
            "health": _build_health_payload("unknown"),
            "ports": _build_mapping_payload([], "No published or exposed ports"),
            "mounts": _build_mapping_payload([], "No mounted volumes or binds"),
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
    inspect_url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/json"
    try:
        inspect_response = session.get(inspect_url)
    except Exception as exc:
        return {"error": f"Failed to fetch stats: {exc}"}

    if inspect_response.status_code != 200:
        return {"error": f"Failed to fetch stats (HTTP {inspect_response.status_code})"}

    inspect_payload = inspect_response.json() or {}
    state = inspect_payload.get("State") or {}
    status = str(state.get("Status") or "unknown").lower()
    health = state.get("Health") or {}
    base_payload = {
        "state_status": status,
        "started_at": str(state.get("StartedAt") or ""),
        "health_status": str(health.get("Status") or "unknown").lower(),
        "port_mappings": _collect_port_mappings(inspect_payload.get("NetworkSettings") or {}),
        "mount_mappings": _collect_mount_mappings(inspect_payload.get("Mounts") or []),
    }

    if status != "running":
        return {
            **base_payload,
            "pids_stats": {"current": int(state.get("Pid") or 0)},
        }

    stats_url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/stats"
    try:
        response = session.get(stats_url, params={"stream": 0})
    except Exception as exc:
        return {"error": f"Failed to fetch stats: {exc}", "state_status": status}

    if response.status_code != 200:
        return {
            **base_payload,
            "error": f"Failed to fetch stats (HTTP {response.status_code})",
        }

    payload = response.json() or {}
    payload.update(base_payload)
    return payload


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


def _push_history(history: list[float], value: float, limit: int = 36) -> list[float]:
    next_history = history + [max(0.0, value)]
    if len(next_history) > limit:
        return next_history[-limit:]
    return next_history


def _parse_percent(value: str) -> float | None:
    if not value.endswith("%"):
        return None
    try:
        return float(value[:-1])
    except Exception:
        return None


def _render_metric_card(payload: dict[str, Any], width: int = 24) -> str:
    if not payload:
        return "No samples yet"
    if "plain_lines" in payload:
        return "\n".join(str(line) for line in (payload.get("plain_lines") or []))
    if "sections" in payload:
        parts = []
        for section in payload.get("sections") or []:
            label = str(section.get("label") or "")
            display = str(section.get("display") or "--")
            subtitle = str(section.get("subtitle") or "")
            filled = int(section.get("filled") or 0)
            filled = max(0, min(width, filled))
            bar = "█" * filled + "░" * (width - filled)
            parts.append(f"{label}  {display}\n{bar}\n{subtitle}")
        return "\n\n".join(parts)
    value = float(payload.get("value") or 0.0)
    scale_max = float(payload.get("scale_max") or 0.0)
    display = str(payload.get("display") or "--")
    unit = str(payload.get("unit") or "")
    avg = float(payload.get("avg") or 0.0)
    maximum = float(payload.get("max") or 0.0)
    filled = 0 if scale_max <= 0 else int(round((value / scale_max) * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    avg_text = _format_chart_value(avg, unit)
    max_text = _format_chart_value(maximum, unit)
    return f"{display}\n{bar}\nAvg {avg_text}   Max {max_text}"


def _format_chart_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "/s":
        return f"{_bytes_to_human(int(value))}/s"
    return f"{value:.1f}"


def _history_avg(values: list[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _build_split_metric(label: str, history: list[float], unit: str, total: int) -> dict[str, Any]:
    current = history[-1] if history else 0.0
    peak = max(history) if history else 0.0
    scale_max = peak if peak > 0 else 1.0
    filled = int(round((current / scale_max) * 24)) if scale_max > 0 else 0
    subtitle = f"Total {_bytes_to_human(total)}" if total > 0 else f"No {label.lower()} activity"
    return {
        "label": label,
        "display": _format_chart_value(current, unit) if history else "--",
        "filled": filled,
        "subtitle": subtitle,
    }


def _build_process_payload(pids_current: int) -> dict[str, Any]:
    scale_max = max(32.0, float(pids_current))
    return {
        "value": float(pids_current),
        "display": str(pids_current),
        "avg": float(pids_current),
        "max": float(pids_current),
        "unit": "",
        "scale_max": scale_max,
        "subtitle": "Active process count",
    }


def _build_state_payload(state_status: str) -> dict[str, Any]:
    normalized = str(state_status or "unknown").lower()
    state_fill = {
        "running": 100.0,
        "restarting": 70.0,
        "paused": 45.0,
        "created": 20.0,
        "exited": 0.0,
        "dead": 0.0,
    }.get(normalized, 10.0)
    subtitle = {
        "running": "Live metrics available",
        "restarting": "Restart in progress",
        "paused": "Container is paused",
        "created": "Created, not started",
        "exited": "Container is stopped",
        "dead": "Container failed",
    }.get(normalized, "State unavailable")
    return {
        "value": state_fill,
        "display": normalized.upper(),
        "avg": state_fill,
        "max": 100.0,
        "unit": "",
        "scale_max": 100.0,
        "subtitle": subtitle,
    }


def _build_uptime_payload(started_at: str, state_status: str) -> dict[str, Any]:
    seconds = _uptime_seconds(started_at) if state_status == "running" else 0
    hours = seconds / 3600 if seconds > 0 else 0.0
    return {
        "value": min(hours, 24.0),
        "display": _format_duration(seconds) if seconds > 0 else "--",
        "avg": min(hours, 24.0),
        "max": 24.0,
        "unit": "",
        "scale_max": 24.0,
        "subtitle": "Since last container start" if seconds > 0 else "Container is not running",
    }


def _build_health_payload(health_status: str) -> dict[str, Any]:
    normalized = str(health_status or "unknown").lower()
    health_fill = {
        "healthy": 100.0,
        "starting": 55.0,
        "unhealthy": 0.0,
        "none": 15.0,
        "unknown": 15.0,
    }.get(normalized, 15.0)
    subtitle = {
        "healthy": "Container health check passed",
        "starting": "Health check warming up",
        "unhealthy": "Health check failing",
        "none": "No health check configured",
        "unknown": "Health status unavailable",
    }.get(normalized, "Health status unavailable")
    return {
        "value": health_fill,
        "display": normalized.upper(),
        "avg": health_fill,
        "max": 100.0,
        "unit": "",
        "scale_max": 100.0,
        "subtitle": subtitle,
    }


def _build_mapping_payload(lines: list[str], empty_message: str) -> dict[str, Any]:
    visible_lines = lines[:3]
    if len(lines) > 3:
        visible_lines.append(f"+{len(lines) - 3} more")
    return {
        "plain_lines": visible_lines or [empty_message],
    }


def _uptime_seconds(started_at: str) -> int:
    if not started_at or started_at.startswith("0001-01-01"):
        return 0
    try:
        normalized = started_at.replace("Z", "+00:00")
        started = datetime.fromisoformat(normalized)
    except Exception:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds()))


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "--"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _collect_port_mappings(network_settings: dict[str, Any]) -> list[str]:
    ports = network_settings.get("Ports") or {}
    mappings: list[str] = []
    for container_port, bindings in sorted(ports.items()):
        if bindings:
            for binding in bindings:
                host_ip = str((binding or {}).get("HostIp") or "")
                host_port = str((binding or {}).get("HostPort") or "")
                host_label = host_port or "?"
                if host_ip and host_ip not in {"0.0.0.0", "::"}:
                    host_label = f"{host_ip}:{host_label}"
                mappings.append(f"{container_port} <- {host_label}")
        else:
            mappings.append(f"{container_port} internal only")
    return mappings


def _collect_mount_mappings(mounts: list[dict[str, Any]]) -> list[str]:
    mappings: list[str] = []
    for mount in mounts:
        source = str((mount or {}).get("Source") or (mount or {}).get("Name") or "?")
        destination = str((mount or {}).get("Destination") or "?")
        mappings.append(f"{source} -> {destination}")
    return mappings
