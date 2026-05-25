# myipv6

Prints the IPv6 address that your OS uses for outgoing connections — the address a remote server sees and the one to put in an allow list.

Works on macOS and Linux (and any Unix-like system with IPv6).

## Why

Modern operating systems assign multiple IPv6 addresses to each interface. The stable address (DHCPv6/SLAAC) handles inbound traffic, but the kernel prefers **temporary privacy addresses** (RFC 8981) for outgoing connections. A remote allow list needs the outgoing address, not the stable one.

macOS enables temporary privacy addresses by default. Most desktop Linux distributions also enable them by default (controlled by the `net.ipv6.conf.<iface>.use_tempaddr` sysctl, set by NetworkManager or systemd-networkd); server distros may leave them off.

This script asks the kernel which source address it would select, so you get the right one regardless of platform.

## Usage

```
python3 ipv6.py
```

Requires Python 3.6+ and IPv6 connectivity. No dependencies beyond the standard library.

## Note

Temporary privacy addresses rotate periodically. If your allow list stops working, re-run the script to get the current address. For a more durable solution, allow your entire `/64` prefix instead of a single address.

## License

MIT — see [LICENSE](LICENSE).
