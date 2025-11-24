from typing import Optional
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static
from datetime import datetime, timezone
import requests_unixsocket

# Docker socket configuration
DOCKER_SOCKET_URL = "http+unix://%2Fvar%2Frun%2Fdocker.sock/v1.42"
session = requests_unixsocket.Session()

class InfoTab(Container):
    """Info tab widget that displays container information with proper styling and scrolling."""
    
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
    
    def compose(self) -> ComposeResult:
        """Compose the initial UI."""
        # Create a scrollable container that will hold the info
        # Using 'with' ensures proper nesting
        with VerticalScroll(id="info-scroll"):
            yield Container(id="info-container", classes="info-content")

    def compose_info(self, info_data: dict) -> None:
        """Compose the UI with the container information."""
        container = self.query_one("#info-container")
        container.remove_children()
        
        if not info_data:
            container.mount(Static("No container information available"))
            return
        
        for label, value in info_data.items():
            # Create the horizontal line container
            line = Horizontal(classes="info-line")
            
            # Determine label class based on content
            label_classes = "label"
            if "  " in label:  # Network details have indentation
                label_classes += " network-detail"
            
            label_widget = Static(str(label), classes=label_classes)
            
            # Add appropriate classes based on the content type
            classes = ["value"]
            if label == "State:":
                state_value = value.lower().split()[0]  # Take first word for state class
                classes.append(f"state-{state_value}")
            elif any(keyword in label for keyword in ["Network", "Port", "Mount", "Volume"]):
                classes.append("resource-info")
            elif any(keyword in label for keyword in ["Driver", "Scope", "Options"]):
                classes.append("config-info")
            
            value_widget = Static(str(value), classes=" ".join(classes))
            
            # Mount line to container first, then mount widgets to line
            container.mount(line)
            line.mount(label_widget, value_widget)
        
        # Force refresh of the scroll area to recalculate virtual size
        scroll = self.query_one("#info-scroll", VerticalScroll)
        scroll.refresh(layout=True)


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
        try:
            now = datetime.now(timezone.utc).astimezone(dt.tzinfo) if dt.tzinfo else datetime.now(timezone.utc)
            delta = now - dt if now >= dt else dt - now
        except Exception:
            delta = datetime.now(timezone.utc) - (dt.replace(tzinfo=None) if dt.tzinfo else dt)
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

    # Networks - Enhanced network information
    network_settings = data.get("NetworkSettings", {}) or {}
    networks = network_settings.get("Networks", {}) or {}
    
    # Ports
    ports = []
    raw_ports = network_settings.get("Ports", {}) or {}
    for container_port, mappings in raw_ports.items():
        if mappings:
            for m in mappings:
                ports.append(f"{m.get('HostIp', '0.0.0.0')}:{m.get('HostPort')} -> {container_port}")
        else:
            ports.append(f"{container_port} (internal only)")
    ports_str = ", ".join(ports) if ports else "none"

    # Mounts details - Enhanced volume information
    mounts = data.get("Mounts", []) or []
    mounts_lines = []
    for m in mounts:
        src = m.get("Source") or m.get("Name") or "<unknown>"
        dst = m.get("Destination") or m.get("Target") or "<unknown>"
        mtype = m.get("Type", "bind")
        rw = "rw" if m.get("RW", m.get("ReadOnly") is False) else "ro"
        mode = m.get("Mode", "")
        driver = m.get("Driver", "")
        propagation = m.get("Propagation", "")
        
        mount_info = f"{src} -> {dst} ({mtype}, {rw}"
        if mode:
            mount_info += f", mode: {mode}"
        if driver:
            mount_info += f", driver: {driver}"
        if propagation:
            mount_info += f", propagation: {propagation}"
        mount_info += ")"
        mounts_lines.append(mount_info)
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

    # Enhanced Network Information
    network_mode = hostcfg.get("NetworkMode", "default")
    info_dict["Network Mode:"] = network_mode
    
    # Detailed network information for each network
    if networks:
        info_dict["Connected Networks:"] = ", ".join(networks.keys())
        
        for network_name, network_info in networks.items():
            network_id = network_info.get("NetworkID", "")[:12]
            ip_address = network_info.get("IPAddress", "")
            gateway = network_info.get("Gateway", "")
            mac_address = network_info.get("MacAddress", "")
            ip_prefix_len = network_info.get("IPPrefixLen", "")
            global_ipv6 = network_info.get("GlobalIPv6Address", "")
            global_ipv6_prefix = network_info.get("GlobalIPv6PrefixLen", "")
            
            if ip_address:
                info_dict[f"  {network_name} IP:"] = f"{ip_address}/{ip_prefix_len}" if ip_prefix_len else ip_address
            if gateway:
                info_dict[f"  {network_name} Gateway:"] = gateway
            if mac_address:
                info_dict[f"  {network_name} MAC:"] = mac_address
            if global_ipv6:
                info_dict[f"  {network_name} IPv6:"] = f"{global_ipv6}/{global_ipv6_prefix}" if global_ipv6_prefix else global_ipv6
            if network_id:
                info_dict[f"  {network_name} Network ID:"] = network_id

    # Ports information
    info_dict["Ports:"] = ports_str
    
    # DNS information
    dns = hostcfg.get("Dns", [])
    if dns:
        info_dict["DNS Servers:"] = ", ".join(dns)
        
    dns_options = hostcfg.get("DnsOptions", [])
    if dns_options:
        info_dict["DNS Options:"] = ", ".join(dns_options)
        
    dns_search = hostcfg.get("DnsSearch", [])
    if dns_search:
        info_dict["DNS Search:"] = ", ".join(dns_search)
        
    # Extra hosts information
    extra_hosts = hostcfg.get("ExtraHosts", [])
    if extra_hosts:
        info_dict["Extra Hosts:"] = ", ".join(extra_hosts)

    # Enhanced Mounts/Volumes Information
    if mounts:
        info_dict["Mounts:"] = mounts_str
        # Count by type
        mount_types = {}
        for m in mounts:
            mtype = m.get("Type", "unknown")
            mount_types[mtype] = mount_types.get(mtype, 0) + 1
        mount_summary = ", ".join([f"{count} {mtype}" for mtype, count in mount_types.items()])
        info_dict["Mount Summary:"] = mount_summary
    else:
        info_dict["Mounts:"] = "none"

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

    # Add container host information
    info_dict["Hostname:"] = data.get("Config", {}).get("Hostname", "")
    info_dict["Domainname:"] = data.get("Config", {}).get("Domainname", "") or "none"
    
    # Add isolation information
    isolation = hostcfg.get("Isolation", "")
    if isolation:
        info_dict["Isolation:"] = isolation

    return info_dict