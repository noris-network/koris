import copy

from unittest.mock import MagicMock, patch

import pytest

from koris.cloud.openstack import (OSNetwork, get_connection, LoadBalancer)
from koris.cloud import OpenStackAPI
from .testdata import (CONFIG, default_data, mock_listener,
                       mock_pool, mock_member, mock_pool_info)
from koris import MASTER_LISTENER_NAME, MASTER_POOL_NAME


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
def get_os(scope="function"):
    conn = MagicMock()
    lb = LoadBalancer(CONFIG, conn)
    lb._data = default_data()
    lb._id = lb._data.id
    return conn, lb


def test_create_loadbalancer():
    conn = get_connection()

    # All good
    lb = LoadBalancer(CONFIG, conn)
    assert lb
    assert isinstance(lb, LoadBalancer)


def test_master_listener_unitialized_lb(get_os):
    conn, lb = get_os
    lb._data = None
    lb._id = "test"
    assert lb._get_master_listener() is None

    lb._id = None
    lb._data = MagicMock()
    assert lb._get_master_listener() is None

    lb._id = None
    lb._data = None
    assert lb._get_master_listener() is None


def test_get_master_listener_lb_not_found(get_os):
    """
    lb._get_master_listener should return None if an exception is thrown
    while trying to locate the LB
    """

    conn, lb = get_os

    conn.load_balancer.find_load_balancer.return_value = None
    assert lb._get_master_listener() is None


def test_get_master_listener_no_listener_ids(get_os):
    """If a returned LB has no listeners, return None"""

    conn, lb = get_os

    mock_lb = default_data()
    mock_lb.listeners = []
    conn.load_balancer.find_load_balancer.return_value = mock_lb
    assert lb._get_master_listener() is None

    mock_lb.listeners = None
    assert lb._get_master_listener() is None


def test_get_master_listener_invalid_listeners(get_os):
    """If the structure of the lb.listeners dict changes, return None"""

    conn, lb = get_os
    mock_lb = default_data()
    mock_lb.listeners = ["a", "b", "c"]
    conn.load_balancer.find_load_balancer.return_value = mock_lb
    assert lb._get_master_listener() is None

    mock_lb.listeners = "test"
    assert lb._get_master_listener() is None

    mock_lb.listeners = {}
    assert lb._get_master_listener() is None

    mock_lb.listeners = None
    assert lb._get_master_listener() is None


def test_get_master_listener_no_master_listener(get_os):
    """If there are no Listeners with name master-listener, return None"""

    conn, lb = get_os
    conn.load_balancer.find_load_balancer.return_value = default_data()
    conn.load_balancer.find_listener.return_value = None
    assert lb._get_master_listener() is None


def test_get_master_listener_multiple_master_listeners(get_os):
    """
    If there are multiple listeners with name master-listener associated
    to LB, return None.
    """

    conn, lb = get_os
    conn.load_balancer.find_load_balancer.return_value = default_data()
    conn.load_balancer.find_listener.side_effect = [mock_listener(),
                                                    mock_listener(),
                                                    mock_listener()]
    assert lb._get_master_listener() is None


def test_get_master_listener_found_master_listener(get_os):
    """The correct case is returned"""

    conn, lb = get_os

    l1, l2, l3 = mock_listener(), mock_listener(), mock_listener()
    l2.name, l3.name = "dex-listener", "oauth-listener"

    conn.load_balancer.find_load_balancer.return_value = default_data()
    conn.load_balancer.find_listener.side_effect = [l1, l2, l3]
    assert lb._get_master_listener() is not None
    assert l1.default_pool_id is not None
    assert l2.default_pool_id is not None
    assert l3.default_pool_id is not None


def test_pool_info_no_pool(get_os):
    """OpenStack can't find the pool"""

    conn, lb = get_os
    conn.load_balancer.find_pool.return_value = None
    assert lb._pool_info("test") is None


def test_pool_info_no_member(get_os):
    """A Pool has members assigned but they can't be retrieved."""

    conn, lb = get_os
    mp = mock_pool()

    conn.load_balancer.find_pool.return_value = mock_pool()
    conn.load_balancer.find_member.side_effect = [None, None, None]

    pool = lb._pool_info(mp.id)
    assert pool['name'] == mp.name
    assert pool['id'] == mp.id
    assert pool['members'] == []


def test_pool_info_pool_unhappy_names(get_os):
    """A Pool has a naughty name"""

    conn, lb = get_os
    mp = mock_pool()
    conn.load_balancer.find_pool.return_value = mp

    for name in ['', None, '-1', 'False', 'True', 'ヽ༼ຈل͜ຈ༽ﾉ ヽ༼ຈل͜ຈ༽ﾉ', '🐵 🙈']:
        conn.load_balancer.find_member.side_effect = [None, None, None]
        mp.name = name
        pool = lb._pool_info(mp.id)
        assert pool['name'] == mp.name


def test_pool_info_single_member(get_os):
    """Return a single member of the Pool"""

    conn, lb = get_os
    mp = mock_pool()
    mem = mock_member(1)
    conn.load_balancer.find_pool.return_value = mock_pool()
    conn.load_balancer.find_member.side_effect = [mem, None, None]

    pool = lb._pool_info(mp.id)
    assert pool['name'] == mp.name
    assert pool['id'] == mp.id
    assert isinstance(pool, dict)
    assert isinstance(pool['members'], list)
    assert pool['members'][0]['id'] == mem.id
    assert pool['members'][0]['name'] == mem.name
    assert pool['members'][0]['address'] == mem.address


def test_pool_all_members(get_os):
    """Default behaviour, all members are returned"""

    conn, lb = get_os
    mp = mock_pool()
    mem = [mock_member(1), mock_member(2), mock_member(3)]
    conn.load_balancer.find_pool.return_value = mock_pool()
    conn.load_balancer.find_member.side_effect = mem

    pool = lb._pool_info(mp.id)
    assert pool['name'] == mp.name
    assert pool['id'] == mp.id

    for i in range(3):
        assert pool['members'][i]['id'] == mem[i].id
        assert pool['members'][i]['name'] == mem[i].name
        assert pool['members'][i]['address'] == mem[i].address


def test_master_listener_no_listener(get_os):
    _, lb = get_os
    lb._get_master_listener = MagicMock(return_value=None)

    assert lb.master_listener is None


def test_master_listener_no_pool(get_os):
    conn, lb = get_os
    lb._get_master_listener = MagicMock(return_value=mock_listener())
    lb._pool_info = MagicMock(return_value=None)
    master_listener = lb.master_listener

    assert master_listener is not None
    assert isinstance(master_listener, dict)
    assert master_listener['pool'] is None


def test_master_listener_wrong_listener_name(get_os):
    ml = mock_listener()
    ml.name = "test"
    conn, lb = get_os
    lb._get_master_listener = MagicMock(return_value=ml)
    assert lb.master_listener is None


def test_master_listener_single_member(get_os):
    conn, lb = get_os
    lb._get_master_listener = MagicMock(return_value=mock_listener())
    pool_info = mock_pool_info()
    pool_info['members'] = [pool_info['members'][0]]
    lb._pool_info = MagicMock(return_value=pool_info)
    master_listener = lb.master_listener

    assert master_listener is not None
    assert isinstance(master_listener, dict)
    assert isinstance(master_listener['pool'], dict)
    assert isinstance(master_listener['pool']['members'], list)
    assert len(master_listener['pool']['members']) == 1
    assert master_listener['pool']['members'][0]['address'] == pool_info['members'][0]['address'] # noqa
    assert master_listener['pool']['members'][0]['id'] == pool_info['members'][0]['id'] # noqa
    assert master_listener['name'] == MASTER_LISTENER_NAME
    assert master_listener['pool']['name'] == MASTER_POOL_NAME


def test_master_multiple_members(get_os):
    """This is the default case: a master-listener with multiple members"""
    conn, lb = get_os

    mpi = mock_pool_info()
    lb._get_master_listener = MagicMock(return_value=mock_listener())
    lb._pool_info = MagicMock(return_value=mpi)
    master_listener = lb.master_listener

    assert master_listener is not None
    assert isinstance(master_listener, dict)
    assert isinstance(master_listener['pool'], dict)
    assert isinstance(master_listener['pool']['members'], list)
    assert len(master_listener['pool']['members']) == len(mpi['members'])
    assert master_listener['name'] == MASTER_LISTENER_NAME
    assert master_listener['pool']['name'] == MASTER_POOL_NAME

    for i in range(len(mpi['members'])):
        assert master_listener['pool']['members'][i]['address'] == mpi['members'][i]['address'] # noqa
        assert master_listener['pool']['members'][i]['id'] == mpi['members'][i]['id']


def test_loadbalancer_with_invalid_subnet():
    lb = LoadBalancer(CONFIG, MagicMock())
    assert lb.subnet == CONFIG['private_net']['subnet']['name']

    config = copy.deepcopy(CONFIG)
    del config['private_net']
    print(config)
    lb = LoadBalancer(config, MagicMock())

    assert lb
    assert lb.subnet == lb.name
