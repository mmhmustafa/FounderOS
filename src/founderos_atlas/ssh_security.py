"""SSH algorithm policy shared by discovery and interactive console paths."""

# CVE-2026-44405 / PYSEC-2026-2858 affects Paramiko's SHA-1 RSA signature
# support.  Netmiko 4.7 requires Paramiko <5, so Atlas explicitly disables the
# affected algorithm on every Paramiko/Netmiko connection until a compatible
# fixed dependency is available.  RSA SHA-2 remains available.
DISABLED_SSH_ALGORITHMS = {
    "keys": ["ssh-rsa"],
    "pubkeys": ["ssh-rsa"],
}


def disabled_ssh_algorithms() -> dict[str, list[str]]:
    """Return a defensive copy suitable for Paramiko/Netmiko kwargs."""

    return {name: list(values) for name, values in DISABLED_SSH_ALGORITHMS.items()}
