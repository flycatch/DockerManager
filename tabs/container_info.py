from typing import Optional, List, Tuple
from datetime import datetime
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static
from textual.reactive import reactive
from textual.widgets import Button
import requests_unixsocket
import random
from textual_plotext import PlotextPlot


# Docker socket configuration
DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock/v1.42"
session = requests_unixsocket.Session()

class GraphWidget(Static):
    """Widget for displaying real-time metrics graphs using textual-plotext."""

    cpu_usage = reactive(0.0)
    memory_usage = reactive(0)
    memory_limit = reactive(1)
    network_rx = reactive(0)
    network_tx = reactive(0)

    # mode can be 'cpu', 'memory', or 'network'
    mode = reactive("cpu")

    def __init__(self, container_id: str, mode: str = "cpu", widget_id: str | None = None) -> None:
        # widget_id allows multiple stacked instances with unique ids
        super().__init__(id=(widget_id or "graph-widget"))
        self.container_id = container_id
        # `mode` is declared reactive at class level; assign plain value here
        self.mode = mode
        self.cpu_history: List[float] = [0.0] * 60
        self.memory_history: List[float] = [0.0] * 60
        self.network_history: List[float] = [0.0] * 30
        self.history_index = 0
        self.previous_cpu_total = 0
        self.previous_system_total = 0

    def compose(self) -> ComposeResult:
    # expose plot; use unique plot id derived from this widget's id so multiple
        # GraphWidget instances don't conflict when querying PlotextPlot
        plot_id = f"plot-{self.id}"
        yield PlotextPlot(id=plot_id)

    def on_mount(self) -> None:
        self.initialize_plot()
        self.set_interval(2.0, self.update_metrics)

    def initialize_plot(self) -> None:
        plot_widget = self.query_one(PlotextPlot)
        plt = plot_widget.plt
        plt.clear_figure()
        plt.title("Container Metrics")
        plt.xlabel("Time")
        plt.ylabel("Usage")
        plt.grid(True)
        plt.show()

    async def update_metrics(self) -> None:
        """Fetch stats and update the plot."""
        stats = get_container_stats(
            self.container_id,
            previous_cpu_total=self.previous_cpu_total,
            previous_system_total=self.previous_system_total,
        )

        if stats:
            self.cpu_usage = float(stats.get("cpu_percent", 0.0))
            self.memory_usage = int(stats.get("memory_usage", 0))
            self.memory_limit = int(stats.get("memory_limit", 1))
            self.network_rx = int(stats.get("network_rx", 0))
            self.network_tx = int(stats.get("network_tx", 0))
            self.previous_cpu_total = stats.get("previous_cpu_total", self.previous_cpu_total)
            self.previous_system_total = stats.get("previous_system_total", self.previous_system_total)
        else:
            # Fallback dummy data
            self.cpu_usage = 25.0 + (random.random() * 10)
            self.memory_usage = 500_000_000
            self.memory_limit = 2_000_000_000
            self.network_rx = 100_000 + int(random.random() * 50_000)
            self.network_tx = 80_000 + int(random.random() * 40_000)

        # Update histories
        self.cpu_history[self.history_index % 60] = self.cpu_usage
        mem_percent = (self.memory_usage / self.memory_limit) * 100 if self.memory_limit > 0 else 0.0
        self.memory_history[self.history_index % 60] = mem_percent
        network_kb = (self.network_rx + self.network_tx) / 1024.0
        self.network_history[self.history_index % 30] = network_kb

        self.history_index += 1

        # Redraw plot
        self.update_plot()

    def update_plot(self) -> None:
        plot_widget = self.query_one(PlotextPlot)
        plt = plot_widget.plt
        # Clear the figure before drawing
        plt.clear_figure()

        # Prepare recent data windows
        num_samples = 20
        recent_cpu = self.cpu_history[max(0, self.history_index - num_samples): self.history_index]
        recent_memory = self.memory_history[max(0, self.history_index - num_samples): self.history_index]
        recent_network = self.network_history[max(0, self.history_index - 10): self.history_index]

        # Pad with zeros if we don't have enough history yet
        while len(recent_cpu) < num_samples:
            recent_cpu.insert(0, 0.0)
        while len(recent_memory) < num_samples:
            recent_memory.insert(0, 0.0)
        while len(recent_network) < 10:
            recent_network.insert(0, 0.0)

        # Draw only one metric depending on mode
        if self.mode == "cpu":
            time_indices = list(range(len(recent_cpu)))
            plt.plot(time_indices, recent_cpu, color="red")
            plt.plotsize(80, 20)
            plt.title(f"CPU Usage: {self.cpu_usage:.1f}%")
            plt.xlim(0, max(len(time_indices) - 1, 1))
            # Dynamic y-axis: 5% above the maximum CPU value seen so far to give
            # some headroom and update every iteration.
            try:
                max_seen = max(self.cpu_history) if self.cpu_history else max(recent_cpu) if recent_cpu else 1.0
            except Exception:
                max_seen = max(recent_cpu) if recent_cpu else 1.0
            y_upper = max(1.0, max_seen * 1.05)
            plt.ylim(0, y_upper)

        elif self.mode == "memory":
            time_indices = list(range(len(recent_memory)))
            plt.plot(time_indices, recent_memory, color="blue")
            plt.plotsize(80, 20)
            mem_last = recent_memory[-1] if recent_memory else 0.0
            plt.title(f"RAM Usage: {mem_last:.1f}%")
            plt.xlim(0, max(len(time_indices) - 1, 1))
            # Dynamic y-axis for memory (percentage). Cap at 100% since memory
            # percent shouldn't exceed 100; add 5% headroom based on observed max.
            try:
                mem_max_seen = max(self.memory_history) if self.memory_history else max(recent_memory) if recent_memory else 0.0
            except Exception:
                mem_max_seen = max(recent_memory) if recent_memory else 0.0
            mem_upper = max(1.0, mem_max_seen * 1.05)
            mem_upper = min(mem_upper, 100.0)
            plt.ylim(0, mem_upper)

        else:  # network
            network_indices = list(range(len(recent_network)))
            network_max = max(recent_network) if recent_network else 100
            plt.plot(network_indices, recent_network, color="green")
            plt.plotsize(80, 20)
            net_last = recent_network[-1] if recent_network else 0.0
            plt.title(f"Network: {net_last:.0f} KB/s")
            plt.xlim(0, max(len(network_indices) - 1, 1))
            plt.ylim(0, max(1, network_max * 1.2))

        # Render
        plt.show()
        plot_widget.refresh()


class InfoTab(Container):
    """Info tab widget that displays container information with real-time graphs."""
    
    def __init__(self, container_id: str) -> None:
        super().__init__(id="info-tab")
        self.container_id = container_id
        self.loading = True
    
    def on_mount(self) -> None:
        # Fetch container info asynchronously
        self.call_later(self.load_info)
    
    def load_info(self) -> None:
        """Load container information and update the UI."""
        info_data = get_container_info_dict(self.container_id)
        print(f"Fetched info data: {info_data}")  # Debug print
        self.loading = False
        self.compose_info(info_data)
        self.refresh()
    
    def compose(self) -> ComposeResult:
        """Compose the UI with horizontal split (50/50)."""
        with Horizontal(id="main-container"):
            with Container(id="info-container") as info:
                info.border_title = "📄 Container Info"

            with Container(id="graphs-container") as graphs:
                graphs.border_title = "📊 Real-time Metrics"
                # Stack three non-clickable graphs vertically: CPU, RAM, Network
                with Vertical(id="graphs-stack"):
                    # Each GraphWidget is wrapped in a container so they stack and
                    # can display individual titles/frames. This helps prevent one
                    # plot from occupying the entire right side.
                    with Container(id="graph-box-cpu"):
                        yield GraphWidget(self.container_id, mode="cpu", widget_id="graph-cpu")
                    with Container(id="graph-box-ram"):
                        yield GraphWidget(self.container_id, mode="memory", widget_id="graph-ram")
                    with Container(id="graph-box-net"):
                        yield GraphWidget(self.container_id, mode="network", widget_id="graph-net")

    def on_button_pressed(self, event) -> None:
        """Handle button presses for switching graph mode."""
        button_id = getattr(event.button, 'id', None)
        gw = None
        try:
            gw = self.query_one(GraphWidget)
        except Exception:
            gw = None

        if not gw:
            return

        if button_id == "btn-cpu":
            gw.mode = "cpu"
        elif button_id == "btn-ram":
            gw.mode = "memory"
        elif button_id == "btn-net":
            gw.mode = "network"

        # Force immediate redraw
        try:
            gw.update_plot()
        except Exception:
            pass


    def compose_info(self, info_data: dict) -> None:
        """Compose the UI with the container information."""
        if not info_data:
            self.query_one("#info-container").mount(Static("No container information available"))
            return

        container = self.query_one("#info-container")
        container.remove_children()
        
        # Remove the scroll container and mount directly to the main container
        for label, value in info_data.items():
            # Create the line container and mount it first
            line = Horizontal(classes="info-line")
            container.mount(line)
            
            # Now that line is mounted, we can add children to it
            label_widget = Static(content=str(label), classes="label")  # Fixed: use keyword argument
            
            # Add appropriate classes based on the content type
            classes = ["value"]
            if label == "State:":
                # Handle state values safely
                state_value = str(value).lower() if value else "unknown"
                classes.append(f"state-{state_value}")
            elif label in ["Networks:", "Ports:", "Mounts:"]:
                classes.append(label.lower().rstrip(':'))
            
            value_widget = Static(content=str(value), classes=" ".join(classes))  # Fixed: use keyword argument
            
            # Mount children to the already-mounted line
            line.mount(label_widget)
            line.mount(value_widget)


def get_container_stats(container_id: str, previous_cpu_total: int = 0, previous_system_total: int = 0) -> Optional[dict]:
    """Fetch container statistics for real-time metrics with proper CPU calculation."""
    try:
        url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/stats?stream=false"
        resp = session.get(url)
        if resp.status_code != 200:
            return None
            
        data = resp.json()
        
        # Get current CPU and system usage
        cpu_stats = data.get('cpu_stats', {})
        precpu_stats = data.get('precpu_stats', {})
        
        cpu_total = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
        system_total = cpu_stats.get('system_cpu_usage', 0)
        
        # Calculate CPU percentage based on difference from previous reading
        cpu_percent = 0.0
        if previous_cpu_total > 0 and previous_system_total > 0 and system_total > previous_system_total:
            cpu_delta = cpu_total - previous_cpu_total
            system_delta = system_total - previous_system_total
            online_cpus = cpu_stats.get('online_cpus', 1)
            
            if system_delta > 0 and online_cpus > 0:
                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100
        
        # Memory usage
        memory_usage = data.get('memory_stats', {}).get('usage', 0)
        memory_limit = data.get('memory_stats', {}).get('limit', 0)
        
        # Convert to integers
        memory_usage = int(memory_usage) if memory_usage else 0
        memory_limit = int(memory_limit) if memory_limit else 1
        
        # Network statistics
        networks = data.get('networks', {})
        network_rx = 0
        network_tx = 0
        
        for net_stats in networks.values():
            network_rx += int(net_stats.get('rx_bytes', 0))
            network_tx += int(net_stats.get('tx_bytes', 0))
        
        return {
            'cpu_percent': float(cpu_percent),
            'memory_usage': memory_usage,
            'memory_limit': memory_limit,
            'network_rx': network_rx,
            'network_tx': network_tx,
            'previous_cpu_total': cpu_total,
            'previous_system_total': system_total
        }
        
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return None

def get_container_info_dict(container_id: str) -> dict:
    """Fetch detailed container info and return as a dictionary."""
    url = f"{DOCKER_SOCKET_URL}/containers/{container_id}/json"
    # Add size=1 parameter to get container size information
    resp = session.get(url, params={"size": 1})
    if resp.status_code != 200:
        return {"Error": f"Failed to fetch container info (HTTP {resp.status_code})"}

    data = resp.json()
    
    # Helper functions
    def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    def _fmt_delta(dt: Optional[datetime]) -> str:
        if not dt:
            return "unknown"
        now = datetime.utcnow().replace(tzinfo=dt.tzinfo) if dt.tzinfo else datetime.utcnow()
        try:
            delta = now - dt if now >= dt else dt - now
        except Exception:
            delta = datetime.utcnow() - dt.replace(tzinfo=None)
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or (days and (minutes or seconds)):
            parts.append(f"{hours}h")
        if minutes or (hours and seconds):
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return " ".join(parts)

    def _bytes_to_human(b: Optional[int]) -> str:
        if not b and b != 0:
            return "unlimited"
        try:
            b = int(b)
        except Exception:
            return str(b)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if b < 1024:
                return f"{b}{unit}"
            b = b // 1024
        return f"{b}PiB"

    # Extract and format container information
    name = data.get("Name", "").lstrip("/")
    image_ref = data.get("Config", {}).get("Image", "unknown")
    image_id = data.get("Image", "")[:12]
    state = data.get("State", {}) or {}
    state_status = state.get("Status", "unknown")
    created_raw = data.get("Created")
    created_dt = _parse_iso(created_raw)
    created_str = created_dt.strftime("%Y-%m-%d %H:%M:%S") if created_dt else str(created_raw)

    # Started / finished
    started_raw = state.get("StartedAt")
    finished_raw = state.get("FinishedAt")
    started_dt = _parse_iso(started_raw)
    finished_dt = _parse_iso(finished_raw)
    uptime = _fmt_delta(started_dt) if started_dt else "not started"

    # Health
    health = state.get("Health") or {}
    health_status = health.get("Status")
    health_log = health.get("Log", [])
    last_health_check = None
    if health_log:
        last_entry = health_log[-1]
        last_time = last_entry.get("End") or last_entry.get("Start")
        last_health_dt = _parse_iso(last_time)
        last_health_check = last_health_dt.strftime("%Y-%m-%d %H:%M:%S") if last_health_dt else None

    # HostConfig / resources
    hostcfg = data.get("HostConfig", {}) or {}
    restart_policy = (hostcfg.get("RestartPolicy") or {}).get("Name", "no")
    memory = hostcfg.get("Memory") or hostcfg.get("MemoryLimit")
    cpu_shares = hostcfg.get("CpuShares")
    cpu_quota = hostcfg.get("CpuQuota")
    cpuset = hostcfg.get("CpusetCpus")
    # Attempt to compute cpus from quota/period if present
    cpu_period = hostcfg.get("CpuPeriod")
    cpus_from_quota = None
    try:
        if cpu_quota and cpu_period:
            cpus_from_quota = round(int(cpu_quota) / int(cpu_period), 2)
    except Exception:
        cpus_from_quota = None

    # Command / entrypoint / working dir / user
    cmd = " ".join(data.get("Config", {}).get("Cmd") or []) or "<none>"
    entrypoint = " ".join(data.get("Config", {}).get("Entrypoint") or []) or "<none>"
    workdir = data.get("Config", {}).get("WorkingDir", "")
    user = data.get("Config", {}).get("User", "") or "<default>"

    # Networks
    networks = list((data.get("NetworkSettings", {}) .get("Networks") or {}).keys())
    # Ports
    ports = []
    raw_ports = (data.get("NetworkSettings", {}) .get("Ports") or {}) or {}
    for container_port, mappings in raw_ports.items():
        if mappings:
            for m in mappings:
                ports.append(f"{m.get('HostIp')}:{m.get('HostPort')} -> {container_port}")
        else:
            ports.append(f"{container_port} (internal only)")
    ports_str = ", ".join(ports) if ports else "none"

    # Mounts details
    mounts = data.get("Mounts", []) or []
    mounts_lines = []
    for m in mounts:
        src = m.get("Source") or m.get("Name") or "<unknown>"
        dst = m.get("Destination") or m.get("Target") or "<unknown>"
        mtype = m.get("Type", "bind")
        rw = "rw" if m.get("RW", m.get("ReadOnly") is False) else "ro"
        mounts_lines.append(f"{src} -> {dst} ({mtype}, {rw})")
    mounts_str = "\n".join(mounts_lines) if mounts_lines else "none"

    # Env and labels
    env_list = data.get("Config", {}).get("Env") or []
    env_count = len(env_list)
    env_preview = env_list[:6]
    labels = data.get("Config", {}).get("Labels") or {}
    labels_lines = [f"{k}={v}" for k, v in (labels.items() if labels else [])]
    labels_str = ", ".join(labels_lines) if labels_lines else "none"

    # PID / OOM / Restarting
    pid = state.get("Pid")
    oom_killed = state.get("OOMKilled", False)
    restarting = state.get("Restarting", False)
    exit_code = state.get("ExitCode", None)

    # Sizes
    size_rw = data.get("SizeRw")
    size_rootfs = data.get("SizeRootFs")
    size_rw_str = _bytes_to_human(size_rw) if size_rw is not None else "unknown"
    size_rootfs_str = _bytes_to_human(size_rootfs) if size_rootfs is not None else "unknown"

    # Build info dictionary
    info_dict = {
        "Name:": name,
        "ID:": data.get('Id', '')[:12],
        "Image:": f"{image_ref} ({image_id})",
        "Created:": created_str,
        "State:": state_status,
        "Started At:": started_dt.strftime('%Y-%m-%d %H:%M:%S') if started_dt else 'n/a',
        "Finished At:": finished_dt.strftime('%Y-%m-%d %H:%M:%S') if finished_dt else 'n/a',
        "Uptime:": uptime,
        "Platform:": data.get("Platform", ""),
        "Driver:": data.get("Driver", ""),
    }

    # Health
    if health_status:
        info_dict["Health:"] = f"{health_status} (last: {last_health_check or 'n/a'})"

    # Resources & host config
    info_dict["Restart Policy:"] = restart_policy
    info_dict["Memory limit:"] = _bytes_to_human(memory)
    info_dict["Memory Swappiness:"] = str(hostcfg.get("MemorySwappiness", "default"))
    info_dict["Memory Swap:"] = _bytes_to_human(hostcfg.get("MemorySwap"))
    info_dict["Memory Reservation:"] = _bytes_to_human(hostcfg.get("MemoryReservation"))
    
    if cpu_shares:
        info_dict["CPU shares:"] = str(cpu_shares)
    if cpus_from_quota:
        info_dict["CPUs (quota):"] = str(cpus_from_quota)
    if cpuset:
        info_dict["CPU set:"] = cpuset
        
    # Add security information
    security_opt = hostcfg.get("SecurityOpt", [])
    if security_opt:
        info_dict["Security Options:"] = ", ".join(security_opt)
    
    privileged = hostcfg.get("Privileged", False)
    if privileged:
        info_dict["Privileged:"] = "true (elevated permissions)"
        
    # Add logging information
    log_config = hostcfg.get("LogConfig", {})
    if log_config:
        log_type = log_config.get("Type", "")
        log_opts = log_config.get("Config", {})
        if log_type:
            info_dict["Logging Driver:"] = log_type
        if log_opts:
            info_dict["Log Options:"] = ", ".join(f"{k}={v}" for k, v in log_opts.items())
            
    # Add resource limits
    pids_limit = hostcfg.get("PidsLimit")
    if pids_limit:
        info_dict["PIDs Limit:"] = str(pids_limit)
        
    ulimits = hostcfg.get("Ulimits", [])
    if ulimits:
        ulimit_strs = []
        for ulimit in ulimits:
            name = ulimit.get("Name", "")
            soft = ulimit.get("Soft", "")
            hard = ulimit.get("Hard", "")
            if name:
                ulimit_strs.append(f"{name}: soft={soft}, hard={hard}")
        if ulimit_strs:
            info_dict["Ulimits:"] = "\n".join(ulimit_strs)

    # Command / runtime
    info_dict["Entrypoint:"] = entrypoint
    info_dict["Command:"] = cmd
    info_dict["Workdir:"] = workdir or 'none'
    info_dict["User:"] = user

    # Network / ports
    info_dict["Networks:"] = ', '.join(networks) if networks else 'none'
    info_dict["Ports:"] = ports_str
    
    # Add detailed network information
    network_settings = data.get("NetworkSettings", {})
    if network_settings:
        # Add IP Address information
        for network_name, network_info in network_settings.get("Networks", {}).items():
            ip_address = network_info.get("IPAddress")
            gateway = network_info.get("Gateway")
            mac_address = network_info.get("MacAddress")
            if ip_address:
                info_dict[f"IP ({network_name}):"] = ip_address
            if gateway:
                info_dict[f"Gateway ({network_name}):"] = gateway
            if mac_address:
                info_dict[f"MAC ({network_name}):"] = mac_address
                
        # Add DNS information
        dns = hostcfg.get("Dns", [])
        if dns:
            info_dict["DNS Servers:"] = ", ".join(dns)
            
        dns_options = hostcfg.get("DnsOptions", [])
        if dns_options:
            info_dict["DNS Options:"] = ", ".join(dns_options)
            
        dns_search = hostcfg.get("DnsSearch", [])
        if dns_search:
            info_dict["DNS Search:"] = ", ".join(dns_search)
            
        # Add extra hosts information
        extra_hosts = hostcfg.get("ExtraHosts", [])
        if extra_hosts:
            info_dict["Extra Hosts:"] = ", ".join(extra_hosts)

    # Mounts
    info_dict["Mounts:"] = mounts_str

    # Env & labels
    if env_count:
        env_preview_str = ", ".join(env_preview)
        more = f" (+{env_count - len(env_preview)} more)" if env_count > len(env_preview) else ""
        info_dict[f"Env ({env_count}):"] = f"{env_preview_str}{more}"
    else:
        info_dict["Env:"] = "none"
    info_dict["Labels:"] = labels_str

    # State details
    info_dict["PID:"] = str(pid) if pid else 'n/a'
    info_dict["OOMKilled:"] = str(oom_killed)
    info_dict["Restarting:"] = str(restarting)
    if exit_code is not None:
        info_dict["ExitCode:"] = str(exit_code)

    # Sizes
    info_dict["Size (rw):"] = size_rw_str
    info_dict["RootFs size:"] = size_rootfs_str

    return info_dict