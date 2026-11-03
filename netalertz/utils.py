"""Small shared helpers: time, formatting, networking and subprocesses."""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Iterable

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def utcnow() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_str() -> str:
    """Return the current UTC timestamp in database format."""
    return utcnow().strftime(TS_FORMAT)


def parse_ts(value: str | None) -> datetime | None:
    """Parse a stored UTC timestamp into an aware datetime."""
    if not value:
        return None
    try:
        cleaned = str(value).replace("T", " ").split(".")[0]
        return datetime.strptime(cleaned, TS_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def local_ts(value: str | None) -> str:
    """Convert a stored UTC timestamp to a compact local time string."""
    dt = parse_ts(value)
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%d %b %H:%M")


def local_time(value: str | None) -> str:
    """Convert a stored UTC timestamp to a local HH:MM time string."""
    dt = parse_ts(value)
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%H:%M")


def ago(value: str | None, suffix: bool = True) -> str:
    """Return a human readable 'time ago' label."""
    dt = parse_ts(value)
    if dt is None:
        return "never"
    seconds = max(0, int((utcnow() - dt).total_seconds()))
    if seconds < 10:
        text = "just now"
    elif seconds < 60:
        text = f"{seconds}s"
    elif seconds < 3600:
        text = f"{seconds // 60}m"
    elif seconds < 86400:
        text = f"{seconds // 3600}h"
    else:
        text = f"{seconds // 86400}d"
    if text == "just now" or not suffix:
        return text
    return f"{text} ago"


def human_duration(seconds: float | int | None) -> str:
    """Format a duration in seconds using the two largest units."""
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def human_bytes(value: float | int | None) -> str:
    """Format a byte count as KB/MB/GB."""
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def normalize_mac(value: str | None) -> str:
    """Normalise a MAC address to lowercase colon notation."""
    if not value:
        return ""
    raw = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(raw) != 12:
        return ""
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2)).lower()


def is_mac(value: str | None) -> bool:
    """Return True when the value is a valid MAC address."""
    return bool(value and MAC_RE.match(value))


def is_ip(value: str | None) -> bool:
    """Return True when the value is a valid IP address."""
    try:
        ipaddress.ip_address((value or "").strip())
        return True
    except ValueError:
        return False


def run_command(cmd: list[str], timeout: float = 30) -> tuple[int, str, str]:
    """Run a command with an explicit timeout and capture text output."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _parse_macos_interfaces(text: str) -> list[dict]:
    """Parse macOS ``ifconfig`` output into interface records."""
    interfaces: list[dict] = []
    current: str | None = None
    flags = ""
    for line in text.splitlines():
        if line and not line[0].isspace() and ":" in line:
            current = line.split(":", 1)[0]
            flags = line
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith("inet ") and "netmask" in stripped:
            parts = stripped.split()
            ip = parts[1]
            netmask = parts[parts.index("netmask") + 1] if "netmask" in parts else "0xffffff00"
            try:
                prefix = bin(int(netmask, 16)).count("1") if netmask.startswith("0x") else 24
            except ValueError:
                prefix = 24
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            interfaces.append(
                {
                    "iface": current,
                    "ip": ip,
                    "prefix": prefix,
                    "cidr": str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False)),
                    "up": "UP" in flags,
                }
            )
    return interfaces


def _parse_linux_interfaces(text: str) -> list[dict]:
    """Parse ``ip -4 -o addr show`` output into interface records."""
    interfaces: list[dict] = []
    pattern = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)")
    for line in text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        iface, ip, prefix = match.group(1), match.group(2), int(match.group(3))
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        interfaces.append(
            {
                "iface": iface.split("@")[0],
                "ip": ip,
                "prefix": prefix,
                "cidr": str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False)),
                "up": True,
            }
        )
    return interfaces


def detect_networks() -> list[dict]:
    """Return the machine's active IPv4 networks with interface names."""
    rc, out, _ = run_command(["ifconfig"], timeout=5)
    interfaces = _parse_macos_interfaces(out) if rc == 0 else []
    if not interfaces:
        rc, out, _ = run_command(["ip", "-4", "-o", "addr", "show"], timeout=5)
        if rc == 0:
            interfaces = _parse_linux_interfaces(out)
    if not interfaces:
        ip = local_ip()
        if ip:
            interfaces.append(
                {
                    "iface": "auto",
                    "ip": ip,
                    "prefix": 24,
                    "cidr": str(ipaddress.ip_network(f"{ip}/24", strict=False)),
                    "up": True,
                }
            )
    # Deduplicate by CIDR while keeping the first interface.
    seen: set[str] = set()
    unique = []
    for item in interfaces:
        if item["cidr"] not in seen:
            seen.add(item["cidr"])
            unique.append(item)
    return unique


def local_ip() -> str:
    """Best-effort discovery of the primary local IPv4 address."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


_VIRTUAL_PREFIXES = ("utun", "tun", "tap", "awdl", "llw", "bridge", "docker", "veth", "lo")


def _interface_score(net: dict, primary_ip: str) -> int:
    """Rank interfaces so real LAN adapters win over VPN/virtual ones."""
    iface = str(net.get("iface") or "").lower()
    score = 0
    if net.get("ip") == primary_ip:
        score += 100
    if iface.startswith(("en", "eth", "wlan", "wlp", "wl")):
        score += 40
    if iface.startswith(_VIRTUAL_PREFIXES):
        score -= 80
    cidr = str(net.get("cidr") or "")
    if cidr.startswith(("10.", "172.16.", "192.168.")):
        score += 5
    if net.get("up"):
        score += 2
    return score


def default_network() -> dict | None:
    """Return the most likely physical LAN to scan."""
    networks = detect_networks()
    if not networks:
        return None
    ip = local_ip()
    return max(networks, key=lambda net: _interface_score(net, ip))


def default_gateway(iface: str = "") -> str:
    """Return the IPv4 gateway for an interface, or the system default route."""
    commands = []
    if iface:
        commands.append(["route", "-n", "get", "-ifscope", iface, "default"])
    commands.append(["route", "-n", "get", "default"])
    for command in commands:
        rc, out, _ = run_command(command, timeout=5)
        if rc == 0:
            match = re.search(r"gateway:\s*(\d+\.\d+\.\d+\.\d+)", out)
            if match:
                return match.group(1)
    command = ["ip", "route", "show", "default"]
    if iface:
        command += ["dev", iface]
    rc, out, _ = run_command(command, timeout=5)
    if rc == 0:
        match = re.search(r"via\s+(\d+\.\d+\.\d+\.\d+)", out)
        if match:
            return match.group(1)
    rc, out, _ = run_command(["netstat", "-rn", "-f", "inet"], timeout=5)
    if rc == 0:
        pattern = r"^default\s+(\d+\.\d+\.\d+\.\d+)\s+\S+\s+" + re.escape(iface) if iface else ""
        if pattern:
            match = re.search(pattern, out, re.MULTILINE)
            if match:
                return match.group(1)
        match = re.search(r"^default\s+(\d+\.\d+\.\d+\.\d+)", out, re.MULTILINE)
        if match:
            return match.group(1)
    return ""


def parse_targets(value: str) -> list[str]:
    """Split a comma/newline separated target string into CIDRs."""
    targets = []
    for chunk in re.split(r"[,\n;]+", value or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            targets.append(str(ipaddress.ip_network(chunk, strict=False)))
        except ValueError:
            continue
    return targets


def make_bar(fraction: float, width: int = 12) -> str:
    """Render a simple unicode progress bar."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    return "█" * filled + "░" * (width - filled)


def flatten(items: Iterable[Iterable]) -> list:
    """Flatten one level of nested iterables."""
    return [item for group in items for item in group]


def uptime_from_samples(rows: list[dict]) -> float:
    """Compute uptime fraction from presence sample rows."""
    samples = sum(int(row.get("samples") or 0) for row in rows)
    online = sum(int(row.get("online") or 0) for row in rows)
    return (online / samples) if samples else 0.0


def timestamp_now_ms() -> int:
    """Return current epoch milliseconds."""
    return int(time.time() * 1000)
