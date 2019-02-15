"""
Test koris.deploy.dex
"""
# pylint: disable=missing-docstring
import asyncio
from unittest import mock

import pytest

from koris.deploy.dex import Dex, ValidationError

NEUTRON = mock.Mock()
LB = mock.MagicMock()
VALID_MEMBERS = ["1.2.3.4", "192.168.0.1"]
INVALID_MEMBERS = ["", 0, "-1", "hello world"]


def test_valid_creation():
    Dex(LB, members=VALID_MEMBERS)


def test_invalid_creation():
    with pytest.raises(ValidationError):
        Dex(LB, members=INVALID_MEMBERS)
    with pytest.raises(ValidationError):
        Dex(None, [])
    with pytest.raises(ValidationError):
        Dex(LB, [])
    with pytest.raises(ValidationError):
        Dex("", "test")
    with pytest.raises(ValidationError):
        Dex(LB, None)
    with pytest.raises(ValidationError):
        Dex(None, None)


def test_valid_parameters():
    dex = Dex(LB, members=VALID_MEMBERS)

    # Test protocol
    dex.protocol = "HTTPS"
    dex.verify()

    # Test port
    dex.listener_port = 32000
    dex.verify()
    dex.listener_port = 0
    dex.verify()
    dex.listener_port = 65535
    dex.verify()
    dex.listener_port = 80
    dex.verify()
    dex.listener_port = 443
    dex.verify()

    # Test algo
    dex.pool_algo = "ROUND_ROBIN"
    dex.verify()
    dex.pool_algo = "LEAST_CONNECTIONS"
    dex.verify()
    dex.pool_algo = "SOURCE_IP"
    dex.verify()


def test_invalid_parameters():
    dex = Dex(LB, members=VALID_MEMBERS)

    # Test protocol
    with pytest.raises(ValidationError):
        dex.protocol = "HTTP"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.protocol = "TCP"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.protocol = "FTP"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.protocol = None
        dex.verify()

    # Test port
    dex = Dex(LB, members=VALID_MEMBERS)
    with pytest.raises(ValidationError):
        dex.listener_port = -1
        dex.verify()
    with pytest.raises(ValidationError):
        dex.listener_port = "hello world"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.listener_port = 1.5
        dex.verify()
    with pytest.raises(ValidationError):
        dex.listener_port = None
        dex.verify()

    # Test algo
    dex = Dex(LB, members=VALID_MEMBERS)
    with pytest.raises(ValidationError):
        dex.pool_algo = "hello world"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.pool_algo = "TEST"
        dex.verify()
    with pytest.raises(ValidationError):
        dex.pool_algo = None
        dex.verify()


def test_valid_configure():
    dex = Dex(LB, members=VALID_MEMBERS)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(dex.configure_lb(NEUTRON))


def test_invalid_configure():
    dex = Dex(LB, members=VALID_MEMBERS)
    dex.protocol = None

    loop = asyncio.get_event_loop()
    with pytest.raises(ValidationError):
        loop.run_until_complete(dex.configure_lb(NEUTRON))
