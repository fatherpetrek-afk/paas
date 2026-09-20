from __future__ import annotations

import socket

import psutil

from control.config import PORT

AF_INET = getattr(socket, "AF_INET", 2)

SKIP_NAME = (
    "loopback",
    "vethernet",
    "vmware",
    "virtualbox",
    "hyper-v",
    "docker",
    "wsl",
    "bluetooth",
    "isatap",
    "teredo",
    "vpn",
    "tun",
    "tap",
    "proton",
    "wintun",
    "zerotier",
    "tailscale",
    "wireguard",
    "openvpn",
    "clash",
    "v2ray",
)

APIPA_PREFIX = "169.254."


def _skip_name(name: str) -> bool:
    lower = name.lower()
    return any(token in lower for token in SKIP_NAME)


def _kind(name: str, ip: str) -> str:
    lower = name.lower()
    if ip.startswith("192.168.137.") and ip.endswith(".1"):
        return "pc_hotspot"
    if ip.startswith("172.20.10."):
        return "iphone_hotspot"
    if "wlan" in lower or "wi-fi" in lower or "wifi" in lower or "无线" in name:
        return "wifi"
    if "ethernet" in lower or "以太网" in name:
        return "ethernet"
    return "other"


def adapters() -> list[dict]:
    stats = psutil.net_if_stats()
    out: list[dict] = []
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if st is not None and not st.isup:
            continue
        if _skip_name(name):
            continue
        for addr in addrs:
            if addr.family != AF_INET:
                continue
            ip = addr.address
            if not ip or ip.startswith("127.") or ip.startswith(APIPA_PREFIX):
                continue
            kind = _kind(name, ip)
            recommended = kind in {"pc_hotspot", "wifi", "iphone_hotspot", "ethernet"}
            warning = None
            if kind == "iphone_hotspot" and not ip.endswith(".1"):
                warning = (
                    "电脑和 iPad 都连手机热点时，苹果常会隔离设备，所以会时通时断。"
                    "更稳：电脑开「移动热点」，iPad 去连电脑。"
                )
            out.append(
                {
                    "name": name,
                    "ip": ip,
                    "url": f"http://{ip}:{PORT}",
                    "kind": kind,
                    "recommended": recommended,
                    "warning": warning,
                }
            )
    out.sort(key=lambda a: {"pc_hotspot": 0, "wifi": 1, "iphone_hotspot": 2, "ethernet": 3, "other": 4}[a["kind"]])
    return out


def access_info() -> dict:
    items = adapters()
    recommended = next((a for a in items if a["recommended"]), items[0] if items else None)
    warnings = [a["warning"] for a in items if a.get("warning")]
    return {
        "port": PORT,
        "local_url": f"http://127.0.0.1:{PORT}",
        "lan_urls": [a["url"] for a in items],
        "adapters": items,
        "recommended": recommended,
        "warnings": warnings,
    }
