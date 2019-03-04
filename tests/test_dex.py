# pylint: disable=redefined-outer-name, invalid-name
"""
Test koris.deploy.dex
"""
# pylint: disable=missing-docstring
import asyncio
import copy
import pytest
import tempfile

from unittest import mock

from koris.deploy.dex import (Pool, Listener, create_dex, create_oauth2,
                              ValidationError, DexSSL, create_dex_conf,
                              is_port, is_ip)
from koris.ssl import read_cert

NEUTRON = mock.Mock()
LB = mock.MagicMock()

VALID_NAMES = ["test", "", None, "-42"]
VALID_MEMBERS = ["1.2.3.4", "192.168.0.1"]
VALID_PORTS = [0, 65535, 80, 443, 32000]
VALID_ALGOS = ["ROUND_ROBIN", "LEAST_CONNECTIONS", "SOURCE_IP"]
VALID_PROTOS = ["HTTPS", "HTTP", "TCP", "TERMINATED_HTTPS"]

INVALID_MEMBERS = ["192.168.300.2", "-1", "hello world", []]
INVALID_PORTS = ["100.3t", 1.32, None, [], {}, (), -25]
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


@pytest.fixture()
def default_dex_ssl():
    return DexSSL("/tmp", "noris.de")


@pytest.fixture(scope="function")
def default_conf():
    return {
        "username_claim": "email",
        "groups_claim": "groups",
        "ports": {
            "listener": 32000,
            "service": 32000
        },
        "client": {
            "id": "example-app",
            "ports": {
                "listener": 5555,
                "service": 32555
            }
        }
    }


def test_is_port():
    valid = [0, 1, 5, 80, 443, 65535]
    invalid = [None, "", 1.4, [], {}, ()]
    for p in valid:
        assert is_port(p)
    for p in invalid:
        assert is_port(p) is False


def test_is_ip():
    valid = ["::0", "::", "1.2.3.4", "2001:0db8:0000:0000:0000:ff00:0042:8329"]
    invalid = [0, 1, 2, 3, None, 1.23, [], {}, (), "300.400.500.600"]
    for i in valid:
        assert is_ip(i)
    for i in invalid:
        assert is_ip(i) is False


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


def test_functions_invalid(default_pool, default_listener):
    # A pool needs to be created first before adding members or HM
    pool = default_pool
    with pytest.raises(ValidationError):
        pool.add_members(NEUTRON, LB)
    with pytest.raises(ValidationError):
        pool.add_health_monitor(NEUTRON, LB)

    # A listener needs a LB to be created
    listener = default_listener
    listener.loadbalancer = None
    with pytest.raises(ValidationError):
        listener.create(NEUTRON)

    # A listener needs to be created first before creating a pool
    listener = default_listener
    listener.listener = None
    with pytest.raises(ValidationError):
        listener.create_pool(NEUTRON)


def test_DexSSL(default_dex_ssl):
    issuers = ["example.org", "1.2.3.4"]
    for i in issuers:
        dex_ssl = DexSSL("/tmp", i, "/test.pem")
        assert dex_ssl is not None
        assert dex_ssl.ca_bundle is not None
        assert dex_ssl.client_bundle is not None

    dex_ssl = default_dex_ssl
    assert dex_ssl is not None
    assert dex_ssl.ca_bundle is not None
    assert dex_ssl.client_bundle is not None

    # Test create_certs
    dex_ssl.issuer = "google.com"
    dex_ssl.create_certs()
    assert dex_ssl.ca_bundle is not None
    assert dex_ssl.client_bundle is not None

    dex_ssl.issuer = None
    with pytest.raises(ValidationError):
        dex_ssl.create_certs()

    # Test save_certs
    with tempfile.TemporaryDirectory() as temp_cert_dir:
        dex_ssl = DexSSL(temp_cert_dir, "noris.de")
        assert dex_ssl is not None
        assert dex_ssl.ca_bundle is not None
        assert dex_ssl.client_bundle is not None

        dex_ssl.save_certs()
        read_cert(f"{temp_cert_dir}/dex-ca.pem")
        read_cert(f"{temp_cert_dir}/dex-client.pem")


def test_DexSSL_invalid():
    # Need certificates before saving them
    with tempfile.TemporaryDirectory() as temp_cert_dir:
        dex_ssl = DexSSL(temp_cert_dir, "noris.de")
        dex_ssl.ca_bundle, dex_ssl.client_bundle = None, None
        with pytest.raises(ValidationError):
            dex_ssl.save_certs()


def test_dex_conf_valid(default_dex_ssl, default_conf):
    config = default_conf
    assert config is not None and isinstance(config, dict)

    dex_ssl = default_dex_ssl
    dex_conf = create_dex_conf(config, dex_ssl)
    assert dex_conf is not None and isinstance(config, dict)


def test_dex_conf_remove_required(default_dex_ssl, default_conf):
    config = default_conf
    dex_ssl = default_dex_ssl

    config = None
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    # Removing required values
    config = copy.deepcopy(default_conf)
    del config["ports"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["client"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["client"]["id"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["ports"]["listener"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["ports"]["service"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["client"]["ports"]["service"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)

    config = copy.deepcopy(default_conf)
    del config["client"]["ports"]["listener"]
    with pytest.raises(ValidationError):
        create_dex_conf(config, dex_ssl)


def test_dex_conf_invalid_ports(default_dex_ssl, default_conf):
    config = default_conf
    dex_ssl = default_dex_ssl

    # Invalid ports
    for port in INVALID_PORTS:
        config['ports']['listener'] = port
        with pytest.raises(ValidationError):
            create_dex_conf(config, dex_ssl)

        config = copy.deepcopy(default_conf)
        config['ports']['service'] = port
        with pytest.raises(ValidationError):
            create_dex_conf(config, dex_ssl)

        config = copy.deepcopy(default_conf)
        config['client']['ports']['listener'] = port
        with pytest.raises(ValidationError):
            create_dex_conf(config, dex_ssl)

        config = copy.deepcopy(default_conf)
        config['client']['ports']['service'] = port
        with pytest.raises(ValidationError):
            create_dex_conf(config, dex_ssl)


def test_dex_conf_remove_optional(default_dex_ssl, default_conf):
    config = default_conf
    dex_ssl = default_dex_ssl

    del config["username_claim"]
    del config["groups_claim"]

    dex_conf = create_dex_conf(config, dex_ssl)
    assert dex_conf["username_claim"] == "email"
    assert dex_conf["groups_claim"] == "groups"
