from unittest.mock import MagicMock

from koris.cloud.openstack import OSNetwork


class Network:
    def __init__(self, name, id):
        self.name = name
        self.id = id


def both_valid_networks(*args, **kwargs):
    return [Network("ext01", "alskdqw1"), Network("ext02", "asodkaklsd22")]


def no_networks(*args, **kwargs):
    return []


def other_networks(*args, **kwargs):
    return [Network("hello", "ajsdlk")]


def valid_plus_other(*args, **kwargs):
    return [Network("hello", "ajsdlk"), Network("ext02", "asodkaklsd22")]


def valid_fallback(*args, **kwargs):
    return [Network("hello", "ajsdlk"), Network("ext01", "asodkaklsd22")]


def test_find_external_network():
    conn = MagicMock()
    conn.network.networks = both_valid_networks

    assert OSNetwork.find_external_network(conn).name == "ext02"


def test_no_external_network():
    conn = MagicMock()
    conn.network.networks = no_networks

    assert OSNetwork.find_external_network(conn) is None


def test_other_networks():
    conn = MagicMock()
    conn.network.networks = other_networks

    assert OSNetwork.find_external_network(conn) is None


def test_valid_plus_other_networks():
    conn = MagicMock()
    conn.network.networks = valid_plus_other

    assert OSNetwork.find_external_network(conn).name == "ext02"


def test_fallback_networks():
    conn = MagicMock()
    conn.network.networks = valid_fallback

    assert OSNetwork.find_external_network(conn).name == "ext01"
