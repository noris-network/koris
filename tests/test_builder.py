"""
Test koris.cloud.builder
"""
import pytest
from unittest import mock

import koris.cloud.openstack

from koris.cloud.openstack import OSClusterInfo
from koris.cloud.builder import NodeBuilder, ControlPlaneBuilder
from koris.ssl import create_certs


DUMMYPORT = {"port": {"admin_state_up": True,
                      "network_id": 'acedfr3c4223ee21',
                      "id": "abcdefg12345678",
                      "fixed_ips": [{"ip_address": "192.168.1.101"}]}}


class DummyServer:  # pylint: disable=too-few-public-methods
    """
    Mock an OpenStack server
    """
    def __init__(self, name, ip_address):

        self.name = name
        self.ip_address = ip_address
        self._exists = False

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
    list(map(lambda x: setattr(x, "_exists", False), nodes))
    assert isinstance(nodes[0], koris.cloud.openstack.Instance)
    assert nodes[0].name == 'node-1-test'

    certs = create_certs(CONFIG, ['node-1-test'], ['192.168.1.103'],
                         write=False)

    lb_ip = '212.58.134.78'
    node_tasks = nb.create_nodes_tasks(certs['ca'], lb_ip,
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
