#!/usr/bin/env python3
#
# Finds the IPv6 address that a remote server's allow list needs to contain —
# the source address the outside world actually sees for your outgoing traffic.
#
# Works on macOS and Linux (and any Unix-like system with IPv6). On Linux, temporary
# privacy addresses are controlled by the net.ipv6.conf.<iface>.use_tempaddr sysctl
# and are enabled by default on most desktop distributions (via NetworkManager or
# systemd-networkd); macOS enables them by default.
#
# A typical host assigns several IPv6 addresses to each active interface:
#
#   - Link-local (fe80::)  — only valid on the local network segment, never routed.
#   - Loopback (::1)       — localhost.
#   - Unique-local / ULA (fc00::/7) — private addresses, like 192.168.x.x in IPv4.
#     Often seen on VPN tunnel interfaces (utun on macOS, tun/wg on Linux).
#   - Global (2000::/3)    — publicly routable, visible to remote machines.
#
# Among global addresses, the OS typically creates:
#
#   1. A stable address assigned via DHCPv6 or stable SLAAC. This address persists
#      across connections. It is recognizable by having a short interface identifier
#      (few hex digits after the /64 prefix), e.g. 2607:fea8:7c0:5000::540a.
#      This is the address others use to reach you (inbound).
#
#   2. Temporary privacy addresses (RFC 8981). The kernel generates these with
#      randomized interface identifiers and PREFERS them for outgoing connections
#      to resist tracking. They rotate periodically.
#
# For a remote allow list, what matters is the SOURCE address of your outgoing
# connections — that's what the remote server sees. The OS uses a temporary privacy
# address for this, NOT the stable one. So the stable address won't work in an
# allow list even though it seems like the "right" choice.
#
# Normally this script asks the OS kernel which source address it would select for
# an outgoing connection (via a UDP socket connect to a public address, no data
# sent). That address is the one to put in the remote allow list.
#
# EXIT NODES: if a Tailscale exit node is active, the kernel routes that socket out
# the Tailscale tunnel, so the source it picks is your node's Tailscale tunnel
# address (fd7a:115c:a1e0::/48) — not publicly routable, and useless in an allow
# list. The real egress happens ON the exit node, where the packet is re-sourced
# with one of the exit node's own addresses, which the local kernel never sees.
# In that case this script falls back to querying an external IPv6 reflector, which
# reports what the public internet actually sees: the exit node's egress address.
#
# Caveat: macOS (and the exit node) rotate temporary addresses, so this address
# will eventually change. For a more durable allow list, consider allowing the
# entire /64 prefix (e.g. 2607:fea8:7c0:5000::/64). The /64 prefix itself is
# controlled by the upstream network and may also change on reboot or lease expiry.

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys

# Tailscale hands out tunnel addresses from this ULA range (fd7a:115c:a1e0::/48).
# A source address in this range means traffic is being routed into the tunnel.
TAILSCALE_ULA_PREFIX = "fd7a:115c:a1e0"

# IPv6-reachable reflectors that echo the caller's source address as plain text.
# Tried in order; the first that answers with a valid IPv6 address wins.
REFLECTORS = ("api6.ipify.org", "v6.ident.me", "ifconfig.co")


def get_local_source_ipv6():
    # Connect a UDP socket to a well-known public IPv6 address (Google DNS).
    # This triggers the kernel's source address selection without sending any data.
    # The OS picks the address it would actually use for outgoing traffic.
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    try:
        sock.connect(("2001:4860:4860::8888", 80))
        return sock.getsockname()[0]
    except OSError as e:
        print(f"No IPv6 connectivity: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        sock.close()


def is_tailscale_address(addr):
    return addr.lower().startswith(TAILSCALE_ULA_PREFIX)


def find_tailscale_cli():
    # Prefer a tailscale on PATH; otherwise fall back to the macOS GUI app's binary.
    cli = shutil.which("tailscale")
    if cli:
        return cli
    candidate = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    return candidate if os.path.exists(candidate) else None


def get_active_exit_node():
    """Return (hostname, [tailscale_ips]) of the active exit node, or None.

    None means the tailscale CLI is missing, not running, or no exit node is
    currently selected — in any of those cases we treat egress as direct.
    """
    cli = find_tailscale_cli()
    if cli is None:
        return None
    try:
        out = subprocess.run(
            [cli, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        status = json.loads(out)
    except json.JSONDecodeError:
        return None
    for peer in (status.get("Peer") or {}).values():
        # "ExitNode" is true only for the peer currently selected as exit node
        # ("ExitNodeOption" merely means the peer is eligible to be one).
        if peer.get("ExitNode"):
            return peer.get("HostName", "?"), peer.get("TailscaleIPs", [])
    return None


class _IPv6HTTPSConnection(http.client.HTTPSConnection):
    # Forces the TCP connection over IPv6 so the reflector observes (and echoes)
    # an IPv6 source — and so the request egresses through the exit node's v6 path.
    def connect(self):
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET6, socket.SOCK_STREAM
        )
        af, socktype, proto, _, sockaddr = infos[0]
        sock = socket.socket(af, socktype, proto)
        sock.settimeout(self.timeout)
        sock.connect(sockaddr)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _http_get_ipv6(host, path="/"):
    conn = _IPv6HTTPSConnection(host, timeout=10)
    try:
        conn.request(
            "GET", path, headers={"User-Agent": "curl/8", "Accept": "text/plain"}
        )
        body = conn.getresponse().read().decode("utf-8", "replace")
    finally:
        conn.close()
    return body.strip()


def is_valid_ipv6(value):
    try:
        socket.inet_pton(socket.AF_INET6, value)
        return True
    except OSError:
        return False


def get_egress_ipv6_via_reflector():
    """Ask an external reflector what source address the public internet sees.

    Returns the echoed IPv6 string, or None if every reflector fails.
    """
    for host in REFLECTORS:
        try:
            answer = _http_get_ipv6(host)
        except OSError:
            continue
        if is_valid_ipv6(answer):
            return answer
    return None


def main():
    local = get_local_source_ipv6()
    exit_node = get_active_exit_node()

    # Direct egress: the kernel's source selection is authoritative.
    if exit_node is None and not is_tailscale_address(local):
        print(local)
        return

    # Egress goes through the Tailscale tunnel, so `local` is a tunnel address that
    # no remote allow list should contain. Query a reflector for the real address.
    if exit_node is not None:
        name, ips = exit_node
        ips_note = f" ({', '.join(ips)})" if ips else ""
        print(
            f"Exit node active: {name}{ips_note}.",
            file=sys.stderr,
        )
    print(
        f"Local source {local} is a Tailscale tunnel address; querying an external "
        "reflector for the egress address the public internet actually sees...",
        file=sys.stderr,
    )

    egress = get_egress_ipv6_via_reflector()
    if egress is None:
        print(
            "Could not determine the egress IPv6 address from any reflector. "
            "Check that the exit node has IPv6 connectivity.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(egress)


if __name__ == "__main__":
    main()
