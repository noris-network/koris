from unittest.mock import MagicMock, patch

import pytest

from koris.cloud.openstack import (OSNetwork, get_connection, LoadBalancer)
from koris.cloud import OpenStackAPI
from .testdata import CONFIG


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


def test_get_connection():
    # All good
    conn = get_connection()
    assert conn

    # RC file not sourced
    with patch.object(OpenStackAPI,
                      'connect',
                      side_effect=OpenStackAPI.exceptions.ConfigException):

        with pytest.raises(SystemExit):
            conn = get_connection()

    # Other error
    with patch.object(OpenStackAPI,
                      'connect',
                      return_value=None):

        with pytest.raises(SystemExit):
            conn = get_connection()


@pytest.fixture
def get_lb(scope="function"):
    conn = get_connection()
    return LoadBalancer(CONFIG, conn)


def test_create_loadbalancer(get_lb):
    conn = get_connection()

    # All good
    lb = LoadBalancer(CONFIG, conn)
    assert lb

    # Test fixture
    lb = get_lb
    assert lb
