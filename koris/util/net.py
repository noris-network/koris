"""Contains utility functions for network stuff"""

from netaddr import valid_ipv4, valid_ipv6
from netaddr.core import AddrFormatError


def is_port(port):
    """Checks if a port is valid"""

    return isinstance(port, int) and 0 <= port <= 65535


def is_ip(ip):
    """Checks if an IP is a valid IPv4 or IPv6 address"""

    return valid_ipv4(ip) or valid_ipv6(ip)

