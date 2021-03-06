"""
Test koris.cloud.builder
"""
#  pylint: disable=redefined-outer-name
import copy
from unittest import mock
from unittest.mock import MagicMock
import pytest
import unittest

from munch import Munch

import koris.cloud.openstack

from koris.cloud.openstack import OSClusterInfo, OSSubnet
from koris.cloud.builder import NodeBuilder, ControlPlaneBuilder
from koris.ssl import (create_certs, CertBundle, create_key, create_ca)

from .testdata import CONFIG

DUMMYPORT = {"port": {"admin_state_up": True,
                      "network_id": 'acedfr3c4223ee21',
                      "id": "abcdefg12345678",
                      "fixed_ips": [{"ip_address": "192.168.1.101"}]}}


class CloudConfig:  # pylint: disable=too-few-public-methods, unnecessary-pass
    """ class CloudConfig """
    pass


class Flavor:  # pylint:  disable=too-few-public-methods
    """ class Flavor """

    def __init__(self, name):

        self.name = name
        self.id = 'abcdefg12345678'


class Test_raise_system_exit(unittest.TestCase):
    def test_instance_naming_with_illegal_chars(self):
        """test using illegal name for instance raises sys.exit"""
        NEUTRON.list_security_groups = mock.MagicMock(
            return_value=iter([{"security_groups": []}]))
        NEUTRON.create_subnet = mock.MagicMock(
            return_value={"subnet": SUBNETS}
        )
        conn = MagicMock()
        config_bad = copy.deepcopy(CONFIG)
        config_bad['cluster-name'] = "illegal:)chars"

        conn.network.networks.return_value = {"name": "ext01"}

        info = OSClusterInfo(NOVA, NEUTRON, CINDER, config_bad, conn)
        with self.assertRaises(SystemExit):
            # assert this raises system exit
            info.nodes_names


def get_ca():
    """ get ca """
    _key = create_key(size=2048)
    _ca = create_ca(_key, _key.public_key(),
                    "DE", "BY", "NUE",
                    "Kubernetes", "CDA-PI",
                    "kubernetes")
    return CertBundle(_key, _ca)


class DummyServer:  # pylint: disable=too-few-public-methods
    """
    Mock an OpenStack server
    """
    def __init__(self, name, ip_address, flavor):

        self.name = name
        self.ip_address = ip_address
        self.flavor = Flavor(flavor)
        self.exists = False

    def interface_list(self):  # pylint: disable=no-self-use
        """ list interfaces"""
        return [DUMMYPORT, ]


NOVA = mock.Mock()
NEUTRON = mock.MagicMock()
CINDER = mock.Mock()
CONN = mock.Mock()

CONFIG2 = {
    "private_net": {},
    "n-nodes": 3,
    "n-masters": 3,
    "keypair": "otiram",
    "availibility-zones": ['nbg6-1a', 'nbg6-1b'],
    "cluster-name": "test",
    "security_group": "test-group",
    "image": "ubuntu 16.04",
    "node_flavor": "ECS.C1.2-4",
    "master_flavor": "ECS.C1.4-8",
    'storage_class': "TestStorageClass"
}

NOVA.keypairs.get = mock.MagicMock(return_value='otiram')
NOVA.glance.find_image = mock.MagicMock(return_value='Ubuntu')
NOVA.flavors.find = mock.MagicMock(return_value=Flavor('ECS.C1.4-8'))
NEUTRON.find_resource = mock.MagicMock(return_value={'id': 'acedfr3c4223ee21'})
NEUTRON.create_port = mock.MagicMock(
    return_value=DUMMYPORT)


NEUTRON.create_security_group = mock.MagicMock(
    return_value={"security_group": {'id':
                                     'e5d896d7-b2bc-4b0c-94ba-c542b4b8e49c',
                                     'name': 'foo-sec'
                                     }})

NEUTRON.list_subnets = mock.MagicMock(
    return_value={'subnets': [{'id': 'e6d899d9-b1bc-4b1c-96ba-c541b4b8e49c',
                               'name': 'foosubnet'}]})

NEUTRON.list_routers.return_value = {
    'routers': [{'id': 'e6d896d9-b1bc-4b1c-96ba-c541b4b5e49c', 'name': 'koris-router'}]}

NEUTRON.list_networks.return_value = {
    'networks': [{'id': 'e7d896d9-b1bc-4b1c-96ba-c541b4b5e49c', 'name': 'koris-network'}]}

NEUTRON.create_network.return_value = {
    'network': {'id': 'e5d896d9-b1bc-4b1c-96ba-c541b4b5e49c', 'name': 'foobar'}}


NEUTRON.list_lbaas_loadbalancers = mock.MagicMock(
    return_value={'loadbalancers': [
        {'admin_state_up': True,
         'description': '',
         'id': '56da500c-bb4d-4037-8d8a-929e98f53e21',
         'listeners': [{'id': '6739c1a6-82a2-4a3b-bc19-71d53212c132'}],
         'name': 'demo2-lb',
         'operating_status': 'ONLINE',
         'pools': [{'id': '7bc7497d-0d05-4023-abc8-f2ab90d8edaa'}],
         'provider': 'octavia',
         'provisioning_status': 'ACTIVE',
         'tenant_id': 'a348bc5b808b4119a199b65b83835d6b',
         'vip_address': '10.32.192.178',
         'vip_port_id': 'ab3c7667-004b-4827-b2dd-a887cdd94199',
         'vip_subnet_id': '01f67963-00eb-4080-a9d9-4cbe936984cd'}]})

SUBNETS = {
    "service_types": [],
    "description": "",
    "updated_at": "2019-01-30T13:47:45Z",
    "cidr": "192.168.0.0/16",
    "ip_version": 4,
    "ipv6_ra_mode": None,
    "host_routes": [],
    "id": "163e7002-3f9a-4b80-bf81-ff01d8bbf270",
    "allocation_pools": [{
        "start": "192.168.0.2",
        "end": "192.168.255.254"
    }],
    "ipv6_address_mode": None,
    "network_id": "04536050-0902-4673-acba-ae54cf7810f6",
    "gateway_ip": "192.168.0.1",
    "name": "bar-baz",
    "subnetpool_id": None,
    "project_id": "f4c0a6de561e487d8ba5d1cc3f1042e8",
    "revision_number": 2,
    "tenant_id": "f4c0a6de561e487d8ba5d1cc3f1042e8",
    "tags": [],
    "dns_nameservers": [],
    "enable_dhcp": True,
    "created_at": "2019-01-30T13:47:45Z"
}


def dummy_create_network(*args, **kwargs):
    return Munch({"id": "x", "name": "test"})


def dummy_ext_network(*args, **kwargs):
    out = Munch()
    out.id = "x"
    out.name = "ext01"
    yield out


@pytest.fixture
def dummy_server():  # pylint: disable=redefined-outer-name
    """ dummy server"""
    return DummyServer("node-1-test",
                       "10.32.192.101",
                       Flavor('ECS.C1.4-8'))


@pytest.fixture
def os_info():  # pylint disable=redefined-outer-name
    """test cluster info class"""
    NEUTRON.list_security_groups = mock.MagicMock(
        return_value=iter([{"security_groups": []}]))
    NEUTRON.create_subnet = mock.MagicMock(
        return_value={"subnet": SUBNETS}
    )

    conn = mock.Mock()
    conn.get_network = dummy_create_network
    conn.create_network = dummy_create_network
    conn.network.networks = dummy_ext_network

    osinfo = OSClusterInfo(NOVA, NEUTRON, CINDER, CONFIG, conn)
    return osinfo


@mock.patch('koris.cloud.OpenStackAPI')
def test_create_network_settings_from_config(patch):
    """test create network from config"""
    NEUTRON.create_subnet = mock.MagicMock(
        return_value={"subnet": SUBNETS}
    )

    sub = OSSubnet('12', CONFIG, CONN)
    subs = sub.get_or_create()
    assert subs.name is not None
    assert subs.cidr is not None


@mock.patch('koris.cloud.OpenStackAPI')
def test_create_network_settings_not_in_config(*args):
    """test create network no settings in config"""
    NEUTRON.create_subnet = mock.MagicMock(
        return_value={"subnet": SUBNETS}
    )
    sub = OSSubnet('12', CONFIG, CONN)
    subs = sub.get_or_create()
    assert subs.name is not None
    assert subs.cidr is not None


@mock.patch('koris.cloud.OpenStackAPI')
# pylint disable=redefined-outer-name
def test_node_builder(patch, os_info, dummy_server):
    """ test the node builder class """
    NOVA.servers.find = mock.MagicMock(return_value=dummy_server)
    nb = NodeBuilder(CONFIG, os_info)
    nodes = nb.get_nodes()
    list(map(lambda x: setattr(x, "exists", False), nodes))
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'node-1-test'

    certs = create_certs(CONFIG, ['node-1-test'], ['192.168.1.103'],
                         write=False)

    lb_ip = '212.58.134.78'
    node_tasks = nb.create_initial_nodes(CloudConfig(), certs['ca'], lb_ip,
                                         "6443",
                                         "123456.abcdefg12345678",
                                         "discovery_hash",
                                         )

    coro_server_create = node_tasks[1]

    call_args = coro_server_create.get_stack()[0].f_locals
    # we go a long way to check that nb.creat_node_tasks
    # will create a future with the correct user data
    assert call_args['keypair'] == 'otiram'
    assert call_args['self'].name == 'node-1-test'
    assert isinstance(call_args['flavor'], Flavor)


def test_controlplane_builder(os_info):  # pylint disable=redefined-outer-name
    """ test the control plane builder class """
    NOVA.servers.find = mock.MagicMock(
        return_value=DummyServer("master-1-test",
                                 "10.32.192.102",
                                 Flavor('ECS.C1.4-8')))
    cpb = ControlPlaneBuilder(CONFIG, os_info)
    masters = cpb.get_masters()
    assert isinstance(masters[0], koris.cloud.openstack.Instance)
    assert masters[0].name == 'master-1-test'


@mock.patch('koris.cloud.OpenStackAPI')
def test_create_nodes(patch, os_info):  # pylint disable=redefined-outer-name
    """ test create nodes"""
    NOVA.servers.list = mock.MagicMock(
        return_value=[DummyServer("test-node-%d" % i,
                                  "10.32.192.10%d" % i,
                                  Flavor('ECS.C1.4-8')) for i in range(1, 4)])
    nb = NodeBuilder(CONFIG, os_info)
    nodes = nb.create_new_nodes('node', "ECS.C1.2-4", "az-west-1")
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'test-node-4'

    nodes = nb.create_new_nodes('node', "ECS.C1.2-4", "az-west-1", amount=3)
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'test-node-4'
    assert nodes[1].name == 'test-node-5'
    assert nodes[2].name == 'test-node-6'


def test_instance_naming_creation(os_info):
    """
    test instance naming uses the pattern
    <cluster-name>-<type>-<number>
    """
    NEUTRON.list_security_groups = mock.MagicMock(
        return_value=iter([{"security_groups": []}]))
    NEUTRON.create_subnet = mock.MagicMock(
        return_value={"subnet": SUBNETS}
    )

    instance_names = os_info.nodes_names
    for i in range(len(instance_names)):
        assert instance_names[i] == 'test-node-{}'.format(i + 1)
