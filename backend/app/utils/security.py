"""SSRF protection helpers for fetching user-supplied URLs."""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_PORTS = {80, 443}
MAX_URL_LEN = 2048


class UnsafeURL(ValueError):
    """The URL is not allowed to be fetched. The message is safe to show to the user."""


@dataclass(frozen=True)
class SafeTarget:
    url: str
    scheme: str
    host: str
    port: int
    ip: str  # the validated address we will actually connect to
    path_qs: str


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    # is_global excludes private, loopback, link-local, reserved, CGNAT, documentation ranges, etc.
    return addr.is_global and not addr.is_multicast


def parse_url(url: str) -> tuple[str, str, int, str]:
    url = (url or "").strip()
    if not url:
        raise UnsafeURL("Please enter a link.")
    if len(url) > MAX_URL_LEN:
        raise UnsafeURL("That link is too long.")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeURL("That link contains invalid characters.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// links are supported.")
    if parts.username or parts.password:
        raise UnsafeURL("Links with embedded usernames or passwords are not supported.")
    host = parts.hostname
    if not host:
        raise UnsafeURL("That doesn't look like a valid link.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise UnsafeURL("That link has an invalid port.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Only standard web ports (80 and 443) are supported.")
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise UnsafeURL("That address isn't a public website.")
    path_qs = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    return parts.scheme, host, port, path_qs


async def resolve_public(host: str, port: int) -> str:
    """Resolve host and return one address, failing if ANY resolved address is non-public (blocks DNS tricks)."""
    try:
        ipaddress.ip_address(host)
        infos = [(None, None, None, None, (host, port))]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=5)
        except (socket.gaierror, asyncio.TimeoutError):
            raise UnsafeURL("We couldn't find that website. Check the link and try again.")
    ips = [i[4][0].split("%")[0] for i in infos]
    if not ips or not all(is_public_ip(ip) for ip in ips):
        raise UnsafeURL("That address isn't a public website.")
    # prefer IPv4 for connectivity
    ips.sort(key=lambda x: ":" in x)
    return ips[0]


async def validate_url(url: str) -> SafeTarget:
    scheme, host, port, path_qs = parse_url(url)
    ip = await resolve_public(host, port)
    return SafeTarget(url=url.strip(), scheme=scheme, host=host, port=port, ip=ip, path_qs=path_qs)
