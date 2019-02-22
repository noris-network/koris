"""Contains utility functions for network stuff"""

from ipaddress import ip_address


def is_port(port):
    """Checks if a port is valid"""

    if not isinstance(port, int):
        return False

    try:
        if not 0 <= port <= 65535:
            return False
    except TypeError:
        return False

    return True


def is_ip(ip):
    """Checks if an IP is a valid IPv4 or IPv6 address"""

    try:
        ip_address(ip)
    except (ValueError, TypeError):
        return False

    return True
