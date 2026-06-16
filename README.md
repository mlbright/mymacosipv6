# myipv6

Prints the IPv6 address that your OS uses for outgoing connections — the address a remote server sees and the one to put in an allow list.

Works on macOS and Linux (and any Unix-like system with IPv6).

## Why

Modern operating systems assign multiple IPv6 addresses to each interface. The stable address (DHCPv6/SLAAC) handles inbound traffic, but the kernel prefers **temporary privacy addresses** (RFC 8981) for outgoing connections. A remote allow list needs the outgoing address, not the stable one.

macOS enables temporary privacy addresses by default. Most desktop Linux distributions also enable them by default (controlled by the `net.ipv6.conf.<iface>.use_tempaddr` sysctl, set by NetworkManager or systemd-networkd); server distros may leave them off.

This script asks the kernel which source address it would select, so you get the right one regardless of platform.

## Tailscale exit nodes

If a Tailscale exit node is active, the kernel routes outgoing traffic into the tunnel, so the source it picks is your node's Tailscale tunnel address (`fd7a:115c:a1e0::/48`) — not publicly routable, and useless in an allow list. The real egress happens **on the exit node**, where the packet is re-sourced with one of the exit node's own addresses, which your local kernel never sees.

When the script detects an active exit node (via `tailscale status --json`) or a tunnel source address, it falls back to querying an external IPv6 reflector, which reports what the public internet actually sees — the exit node's egress address. Diagnostic notes go to stderr; the address itself is the only thing printed to stdout, so piping still works.

## Usage

```
python3 ipv6.py
```

Requires Python 3.6+ and IPv6 connectivity. No dependencies beyond the standard library. The Tailscale CLI is used only if present; without it, the script behaves exactly as before.

## Note

Temporary privacy addresses rotate periodically — and an exit node may use a rotating temporary address for its own egress too. If your allow list stops working, re-run the script to get the current address. For a more durable solution, allow the entire `/64` prefix instead of a single address.

## License

MIT — see [LICENSE](LICENSE).
