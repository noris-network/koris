"""
Test koris.cloud.builder
"""
import pytest
from unittest import mock

import koris.cloud.openstack

from koris.cloud.openstack import OSClusterInfo
from koris.cloud.builder import NodeBuilder, ControlPlaneBuilder
from koris.ssl import (create_certs, CertBundle, create_key, create_ca)


DUMMYPORT = {"port": {"admin_state_up": True,
                      "network_id": 'acedfr3c4223ee21',
                      "id": "abcdefg12345678",
                      "fixed_ips": [{"ip_address": "192.168.1.101"}]}}


def get_ca():
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
    def __init__(self, name, ip_address):

        self.name = name
        self.ip_address = ip_address
        self.exists = False

    def interface_list(self):
        return [DUMMYPORT, ]


NOVA = mock.Mock()
NEUTRON = mock.Mock()
CINDER = mock.Mock()
CONFIG = {
    "n-nodes": 3,
    "n-masters": 3,
    "keypair": "otiram",
    "availibility-zones": ['nbg6-1a', 'nbg6-1b'],
    "cluster-name": "test",
    "private_net": "test-net",
    "security_group": "test-group",
    "image": "ubuntu 16.04",
    "node_flavor": "ECS.C1.2-4",
    "master_flavor": "ECS.C1.4-8",
    'storage_class': "TestStorageClass"
}

NOVA.keypairs.get = mock.MagicMock(return_value='otiram')
NOVA.glance.find_image = mock.MagicMock(return_value='Ubuntu')
NOVA.flavors.find = mock.MagicMock(return_value='ECS.C1.4-8')
NEUTRON.find_resource = mock.MagicMock(return_value={'id': 'acedfr3c4223ee21'})
NEUTRON.create_port = mock.MagicMock(
    return_value=DUMMYPORT)

NEUTRON.create_security_group = mock.MagicMock(
    return_value={"security_group": {'id':
                                     'e5d896d7-b2bc-4b0c-94ba-c542b4b8e49c'}})

NEUTRON.list_subnets = mock.MagicMock(
    return_value={'subnets': [{'id': 'e6d899d9-b1bc-4b1c-96ba-c541b4b8e49c'}]})

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


@pytest.fixture
def os_info():
    NEUTRON.list_security_groups = mock.MagicMock(
        return_value=iter([{"security_groups": []}]))
    osinfo = OSClusterInfo(NOVA, NEUTRON, CINDER, CONFIG)
    return osinfo


def test_node_builder(os_info):
    """ test the node builder class """
    NOVA.servers.find = mock.MagicMock(return_value=DummyServer("node-1-test",
                                                                "10.32.192.101")) # noqa
    nb = NodeBuilder(CONFIG, os_info)
    nodes = nb.get_nodes()
    list(map(lambda x: setattr(x, "exists", False), nodes))
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'node-1-test'

    certs = create_certs(CONFIG, ['node-1-test'], ['192.168.1.103'],
                         write=False)

    lb_ip = '212.58.134.78'
    node_tasks = nb.create_initial_nodes(certs['ca'], lb_ip,
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
    assert call_args['flavor'] == 'ECS.C1.4-8'


def test_controlplane_builder(os_info):
    """ test the control plane builder class """
    NOVA.servers.find = mock.MagicMock(return_value=DummyServer("master-1-test", # noqa
                                                                "10.32.192.102")) # noqa
    cpb = ControlPlaneBuilder(CONFIG, os_info)
    masters = cpb.get_masters()
    assert isinstance(masters[0], koris.cloud.openstack.Instance)
    assert masters[0].name == 'master-1-test'


def test_create_nodes(os_info):
    NOVA.servers.list = mock.MagicMock(
        return_value=[DummyServer("node-%d-test" % i,
                                  "10.32.192.10%d" % i) for i in range(1, 4)])
    nb = NodeBuilder(CONFIG, os_info)
    nodes = nb.create_new_nodes('node', "ECS.C1.2-4", "az-west-1")
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'node-4-test'

    nodes = nb.create_new_nodes('node', "ECS.C1.2-4", "az-west-1", N=3)
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'node-4-test'
    assert nodes[1].name == 'node-5-test'
    assert nodes[2].name == 'node-6-test'
