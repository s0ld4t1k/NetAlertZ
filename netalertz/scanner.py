"""Host discovery backends.

NetAlertZ intentionally shells out to well-known tools instead of re-implementing
raw sockets: ``arp-scan`` when available, ``nmap`` for portable discovery,
``fping`` for fast ping sweeps, and the OS ARP/neighbour cache as a fallback.
"""

from __future__ import annotations

import ipaddress
import re
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from .utils import normalize_mac, parse_targets, run_command

# A compact offline OUI table covering common homelab / office hardware.
OUI: dict[str, str] = {
    "000c29": "VMware",
    "005056": "VMware",
    "080027": "VirtualBox",
    "525400": "QEMU",
    "00163e": "Xen",
    "00155d": "Microsoft",
    "3c5282": "Apple",
    "001b63": "Apple",
    "001451": "Apple",
    "a45e60": "Apple",
    "f01898": "Apple",
    "d0817a": "Apple",
    "b827eb": "Raspberry Pi",
    "dca632": "Raspberry Pi",
    "e45f01": "Raspberry Pi",
    "2ccf67": "Raspberry Pi",
    "840d8e": "Espressif",
    "ecfabc": "Espressif",
    "7c9ebd": "Espressif",
    "246f28": "Espressif",
    "001a79": "Apple",
    "74acb9": "Ubiquiti",
    "f4f5d8": "Ubiquiti",
    "788a20": "Ubiquiti",
    "002468": "Cisco",
    "00000c": "Cisco",
    "f88e85": "Netgear",
    "204e7f": "Netgear",
    "a040a0": "Netgear",
    "001422": "Dell",
    "001874": "Dell",
    "f44d30": "Dell",
    "1c697a": "Dell",
    "3c0754": "HP",
    "00e04c": "HP",
    "d02788": "HP",
    "0017a4": "Lenovo",
    "f4ce46": "Lenovo",
    "002590": "IBM",
    "001cbf": "Supermicro",
    "0013ce": "Samsung",
    "b0be83": "Samsung",
    "bc4c4c": "Samsung",
    "d46e0e": "Sony",
    "001fa7": "Sony",
    "7c04d0": "Nintendo",
    "48b02d": "NVIDIA",
    "00156d": "Amcrest",
    "ac9e17": "Reolink",
    "00408c": "Axis",
    "50c7bf": "TP-Link",
    "003192": "TP-Link",
    "b04e26": "TP-Link",
    "2887ba": "TP-Link",
    "9cb6d0": "Rivet Networks",
    "409f38": "Acer",
    "0017c8": "LG",
    "78dd08": "Hon Hai",
    "f4f26d": "Hon Hai",
    "247777": "Cisco",
    "001dd8": "Microsoft",
    "001e58": "D-Link",
    "1c7ee5": "D-Link",
    "ec2280": "D-Link",
    "001cc0": "Intel",
    "3c9509": "Intel",
    "a4bb6d": "Intel",
    "0024e8": "Dell",
    "94c691": "Shenzhen",
    "c4e984": "TP-Link",
    "188b45": "Cisco",
    "001e8c": "Asustek",
    "04d4c4": "Asustek",
    "2c56dc": "Asustek",
    "0016cb": "Apple",
    "b8e856": "Apple",
    "f0d1a9": "Apple",
}

TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Router", ("router", "gateway", "openwrt", "fritz", "ubiquiti", "unifi", "mikrotik")),
    ("Access Point", ("access point", "wifi", "wireless", "ap-", "eero", "deco")),
    ("Switch", ("switch", "netgear", "tp-link", "d-link")),
    ("Server", ("server", "synology", "qnap", "truenas", "proxmox", "esxi", "nas")),
    ("Camera", ("camera", "cam", "reolink", "hikvision", "amcrest", "axis")),
    ("Printer", ("printer", "hp", "brother", "canon", "epson", "xerox")),
    ("Phone", ("iphone", "pixel", "galaxy", "android", "phone")),
    ("Laptop", ("macbook", "laptop", "notebook", "thinkpad")),
    ("Desktop", ("desktop", "imac", "pc-", "workstation")),
    ("TV", ("tv", "television", "chromecast", "appletv", "roku", "firestick")),
    ("Speaker", ("speaker", "sonos", "echo", "homepod", "audio")),
    ("IoT", ("esp", "tasmota", "shelly", "tuya", "zigbee", "iot", "sensor")),
    ("Game Console", ("playstation", "xbox", "nintendo", "switch")),
]

MAC_RE_DARWIN = re.compile(r"\((?P<ip>\d+\.\d+\.\d+\.\d+)\) at (?P<mac>[0-9a-fA-F:]{17})")
MAC_RE_LINUX = re.compile(
    r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+(?P<mac>[0-9a-fA-F:]{17})"
)
NMAP_HOST_RE = re.compile(r"^Host:\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s+\((?P<name>[^)]*)\)")


@dataclass
class Host:
    """One host observed during discovery."""

    ip: str
    mac: str = ""
    hostname: str = ""
    vendor: str = ""
    source: str = "scan"

    def key(self) -> str:
        """Return a stable identity key (MAC when valid, otherwise IP)."""
        return self.mac or f"ip:{self.ip}"


@dataclass
class DiscoverResult:
    """Discovery output plus diagnostics shown in the Scanners view."""

    hosts: list[Host] = field(default_factory=list)
    method: str = "cache"
    target: str = ""
    error: str = ""
    duration: float = 0.0


class Scanner:
    """Discovers hosts on the local network using available system tools."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._oui = dict(OUI)

    # ------------------------------------------------------------------ tools
    def capabilities(self) -> dict[str, bool]:
        """Return which discovery tools are installed."""
        return {
            "arp-scan": bool(shutil.which("arp-scan")),
            "nmap": bool(shutil.which("nmap")),
            "fping": bool(shutil.which("fping")),
            "ping": bool(shutil.which("ping")),
            "cache": True,
        }

    def effective_method(self) -> str:
        """Resolve the configured method to a usable one."""
        method = str(self.settings.get("discovery_method") or "auto")
        caps = self.capabilities()
        if method != "auto" and caps.get(method):
            return method
        if caps["arp-scan"]:
            return "arp-scan"
        if caps["nmap"]:
            return "nmap"
        if caps["fping"]:
            return "ping"
        return "cache"

    def plan_targets(self) -> list[str]:
        """Return the list of CIDRs that should be scanned."""
        configured = parse_targets(str(self.settings.get("scan_subnets") or ""))
        if configured:
            return configured
        from .utils import default_network

        net = default_network()
        return [net["cidr"]] if net else []

    # --------------------------------------------------------------- discovery
    def discover(self, target: str, progress=None) -> DiscoverResult:
        """Run discovery against one CIDR and merge ARP-cache knowledge."""
        import time

        started = time.monotonic()
        method = self.effective_method()
        if progress:
            progress(f"discovering {target} via {method}")

        hosts: list[Host] = []
        error = ""
        try:
            if method == "arp-scan":
                hosts, error = self._arp_scan(target)
                if error and self.capabilities()["nmap"]:
                    hosts, error = self._nmap(target), ""
                    method = "nmap"
            elif method == "nmap":
                hosts, error = self._nmap(target)
            elif method == "ping":
                hosts, error = self._fping(target)
            else:
                hosts = []
        except Exception as exc:  # pragma: no cover - defensive
            error = str(exc)

        # Merge everything the OS already knows about this subnet.
        cache = self._arp_cache(target)
        by_ip = {host.ip: host for host in hosts}
        for cached in cache:
            existing = by_ip.get(cached.ip)
            if existing:
                if not existing.mac:
                    existing.mac = cached.mac
                if not existing.hostname:
                    existing.hostname = cached.hostname
            else:
                by_ip[cached.ip] = cached
                hosts.append(cached)

        if not hosts and method == "cache":
            error = error or "no hosts in ARP cache"

        self._apply_identity(hosts)
        return DiscoverResult(
            hosts=hosts,
            method=method,
            target=target,
            error=error,
            duration=time.monotonic() - started,
        )

    def _apply_identity(self, hosts: list[Host]) -> None:
        """Fill vendor and type hints for every host."""
        for host in hosts:
            host.mac = normalize_mac(host.mac)
            if not host.vendor and host.mac:
                host.vendor = self.lookup_vendor(host.mac)
            if host.hostname:
                host.hostname = host.hostname.strip().rstrip(".")

    def _timeout(self) -> float:
        """Return the configured per-command timeout."""
        return float(self.settings.get_int("scan_timeout") or 120)

    def _arp_scan(self, target: str) -> tuple[list[Host], str]:
        """Discover hosts with arp-scan (best signal/noise, usually needs root)."""
        cmd = ["arp-scan", "--ignoredups", "--retry=2", "--timeout=500", target]
        iface = str(self.settings.get("scan_interface") or "").strip()
        if iface:
            cmd.insert(1, f"--interface={iface}")
        rc, out, err = run_command(cmd, timeout=self._timeout())
        hosts: list[Host] = []
        for line in out.splitlines():
            match = re.match(
                r"^(?P<ip>\d+\.\d+\.\d+\.\d+)\s+(?P<mac>[0-9a-fA-F:]{17})\s*(?P<vendor>.*)$",
                line.strip(),
            )
            if match:
                hosts.append(
                    Host(
                        ip=match.group("ip"),
                        mac=normalize_mac(match.group("mac")),
                        vendor=match.group("vendor").strip(),
                        source="arp-scan",
                    )
                )
        if rc != 0 and not hosts:
            return [], (err or out or "arp-scan failed").strip()[:300]
        return hosts, ""

    def _nmap(self, target: str) -> tuple[list[Host], str]:
        """Discover hosts with nmap host discovery in greppable mode."""
        cmd = [
            "nmap",
            "-sn",
            "-n",
            "-T4",
            "--min-rate",
            "300",
            "--max-retries",
            "1",
            "--host-timeout",
            "8s",
            "-oG",
            "-",
            target,
        ]
        rc, out, err = run_command(cmd, timeout=self._timeout())
        hosts: list[Host] = []
        for line in out.splitlines():
            if not line.startswith("Host:") or "Status: Up" not in line:
                continue
            match = NMAP_HOST_RE.match(line)
            if not match:
                continue
            hostname = match.group("name") or ""
            hosts.append(Host(ip=match.group("ip"), hostname=hostname, source="nmap"))
        if rc != 0 and not hosts:
            return [], (err or out or "nmap failed").strip()[:300]
        return hosts, ""

    def _fping(self, target: str) -> tuple[list[Host], str]:
        """Discover hosts with a fast fping sweep."""
        cmd = ["fping", "-a", "-q", "-r", "1", "-t", "250", "-g", target]
        rc, out, err = run_command(cmd, timeout=self._timeout())
        hosts = [Host(ip=line.strip(), source="ping") for line in out.splitlines() if line.strip()]
        if rc not in (0, 1) and not hosts:
            return [], (err or "fping failed").strip()[:300]
        return hosts, ""

    def _arp_cache(self, target: str | None = None) -> list[Host]:
        """Read the OS ARP/neighbour cache, optionally limited to a CIDR."""
        rc, out, _ = run_command(["arp", "-an"], timeout=5)
        paired: list[tuple[str, str]] = []
        if rc == 0:
            paired = [(m.group("ip"), m.group("mac")) for m in MAC_RE_DARWIN.finditer(out)]
        if not paired:
            rc, out, _ = run_command(["ip", "neigh", "show"], timeout=5)
            if rc == 0:
                paired = [(m.group("ip"), m.group("mac")) for m in MAC_RE_LINUX.finditer(out)]

        network = None
        if target:
            try:
                network = ipaddress.ip_network(target, strict=False)
            except ValueError:
                network = None

        hosts: list[Host] = []
        seen: set[str] = set()
        for ip, mac in paired:
            normalized = normalize_mac(mac)
            if not normalized or normalized.startswith("ff:ff:ff") or normalized in seen:
                continue
            if network and ipaddress.ip_address(ip) not in network:
                continue
            seen.add(normalized)
            hosts.append(Host(ip=ip, mac=normalized, source="cache"))
        return hosts

    # --------------------------------------------------------------- hostnames
    def resolve_hostnames(self, hosts: list[Host], progress=None) -> None:
        """Resolve reverse DNS names for hosts that don't have one."""
        if not self.settings.get_bool("resolve_names"):
            return
        pending = [host for host in hosts if not host.hostname][:64]
        if not pending:
            return
        if progress:
            progress(f"resolving {len(pending)} hostname(s)")

        def lookup(host: Host) -> tuple[Host, str]:
            try:
                name = socket.gethostbyaddr(host.ip)[0]
                return host, name.split(".")[0] if name else ""
            except (OSError, socket.herror):
                return host, ""

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(lookup, host) for host in pending]
            done, _ = wait(futures, timeout=8)
            for future in done:
                try:
                    host, name = future.result()
                except Exception:
                    continue
                if name and not name.replace("-", "").isdigit():
                    host.hostname = name

    # ------------------------------------------------------------------ vendors
    def lookup_vendor(self, mac: str) -> str:
        """Return a vendor name for a MAC prefix."""
        if not self.settings.get_bool("vendor_lookup"):
            return ""
        normalized = normalize_mac(mac)
        if not normalized:
            return ""
        prefix = normalized.replace(":", "")[:6]
        if prefix in self._oui:
            return self._oui[prefix]
        return ""

    @staticmethod
    def guess_type(vendor: str, hostname: str) -> str:
        """Guess a device type from vendor and hostname keywords."""
        haystack = f"{vendor} {hostname}".lower()
        for label, keywords in TYPE_RULES:
            if any(keyword in haystack for keyword in keywords):
                return label
        return ""
