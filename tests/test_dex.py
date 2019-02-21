# pylint: disable=redefined-outer-name, invalid-name
"""
Test koris.deploy.dex
"""
# pylint: disable=missing-docstring
import asyncio
from unittest import mock

import pytest

from koris.deploy.dex import (Pool, Listener, create_dex, create_oauth2, 
                              ValidationError, create_dex_certs)

NEUTRON = mock.Mock()
LB = mock.MagicMock()

VALID_NAMES = ["test", "", None, "-42"]
VALID_MEMBERS = ["1.2.3.4", "192.168.0.1"]
VALID_PORTS = [0, 65535, 80, 443, 32000]
VALID_ALGOS = ["ROUND_ROBIN", "LEAST_CONNECTIONS", "SOURCE_IP"]
VALID_PROTOS = ["HTTPS", "HTTP", "TCP", "TERMINATED_HTTPS"]

INVALID_MEMBERS = ["", "-1", "hello world", []]
INVALID_PORTS = ["test", 1.32, None, "", [], {}, (), -25]
INVALID_ALGOS = ["", None, 1, 2.3, [], {}, (), "test"]
INVALID_PROTOS = ["UDP"]
INVALID_PROTOS.extend(INVALID_ALGOS)


@pytest.fixture
def default_pool():
    return Pool(VALID_NAMES[0], VALID_PROTOS[0], VALID_PORTS[0], VALID_ALGOS[0],
                VALID_MEMBERS)


@pytest.fixture()
def default_listener(default_pool):
    pool = default_pool
    return Listener(LB, VALID_NAMES[0], VALID_PORTS[0], pool)


# Valid tests
def test_create_valid(default_pool):
    # Pool
    for name in VALID_NAMES:
        for proto in VALID_PROTOS:
            for algo in VALID_ALGOS:
                for port in VALID_PORTS:
                    Pool(name, proto, port, algo, VALID_MEMBERS)

                    for ip in VALID_MEMBERS:
                        Pool(name, proto, port, algo, [ip])

    # Listener
    for name in VALID_NAMES:
        for port in VALID_PORTS:
            for proto in VALID_PROTOS:
                Listener(LB, name, port, default_pool, proto)


def test_change_valid(default_pool, default_listener):
    name = VALID_NAMES[0]
    port = VALID_PORTS[0]
    algo = VALID_ALGOS[0]
    proto = VALID_PROTOS[0]

    # Pool
    pool = default_pool
    for name in VALID_NAMES:
        pool.name = name
        pool.verify()

    for proto in VALID_PROTOS:
        pool.proto = proto
        pool.verify()

    for algo in VALID_ALGOS:
        pool.algorithm = algo
        pool.verify()

    for port in VALID_PORTS:
        pool.port = port
        pool.verify()

    # Listener
    listener = default_listener
    for name in VALID_NAMES:
        listener.name = name
        listener.verify()

    for port in VALID_PORTS:
        listener.port = port
        listener.verify()


def test_functions_valid(default_pool, default_listener):
    name = VALID_NAMES[0]
    port = VALID_PORTS[0]

    # Pool
    pool = default_pool
    listener = default_listener

    # Create a Listener first so it has an ID
    listener.create(NEUTRON)

    pool.create(NEUTRON, LB, listener.id)
    pool.add_members(NEUTRON, LB)
    pool.add_health_monitor(NEUTRON, LB)

    pool = default_pool
    pool.all(NEUTRON, LB, listener.id)

    # Listener
    pool = default_pool
    listener = Listener(LB, name, port, pool)
    listener.create(NEUTRON)
    listener.create_pool(NEUTRON)
    listener.all(NEUTRON)


def test_async_valid():
    loop = asyncio.get_event_loop()
    dex_task = loop.create_task(create_dex(NEUTRON, LB, members=VALID_MEMBERS))
    oauth_task = loop.create_task(create_oauth2(NEUTRON, LB, members=VALID_MEMBERS))
    tasks = [dex_task, oauth_task]
    loop.run_until_complete(asyncio.gather(*tasks))


# Invalid tests
def test_create_invalid(default_pool):
    NAME = VALID_NAMES[0]
    PROTO = VALID_PROTOS[0]
    PORT = VALID_PORTS[0]
    ALGO = VALID_ALGOS[0]

    # Pool
    for proto in INVALID_PROTOS:
        with pytest.raises(ValidationError):
            Pool(NAME, proto, PORT, ALGO, VALID_MEMBERS)

    for port in INVALID_PORTS:
        with pytest.raises(ValidationError):
            Pool(NAME, PROTO, port, ALGO, VALID_MEMBERS)

    for algo in INVALID_ALGOS:
        with pytest.raises(ValidationError):
            Pool(NAME, PROTO, PORT, algo, VALID_MEMBERS)

    for ip in INVALID_MEMBERS:
        with pytest.raises(ValidationError):
            Pool(NAME, PROTO, PORT, ALGO, [ip])

    with pytest.raises(ValidationError):
        Pool(NAME, PROTO, PORT, ALGO, None)

    with pytest.raises(ValidationError):
        Pool(NAME, PROTO, PORT, ALGO, [])

    # Listener
    for port in INVALID_PORTS:
        with pytest.raises(ValidationError):
            Listener(LB, NAME, port, default_pool)


def test_creat_dex_certs():
    HOSTS = ["example.org", "dex.example.com"]

    ca, client = create_dex_certs(ips=VALID_MEMBERS)
    assert ca is not None
    assert client is not None

    for ip in VALID_MEMBERS:
        ca, client = create_dex_certs(ips=[ip])
        assert ca is not None
        assert client is not None

    ca, client = create_dex_certs(hosts=HOSTS)
    assert ca is not None
    assert client is not None

    for host in HOSTS:
        ca, client = create_dex_certs(hosts=[host])
        assert ca is not None
        assert client is not None

    ca, client = create_dex_certs(hosts=HOSTS, ips=VALID_MEMBERS)
    assert ca is not None
    assert client is not None
