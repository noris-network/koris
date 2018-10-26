"""
Test kolt.cloud.builder
"""
from unittest import mock

import kolt.cloud.openstack

from kolt.cloud.builder import NodeBuilder


class DummyServer:  # pylint: disable=too-few-public-methods
    """
    Mock an OpenStack server
    """
    def __init__(self, name):
        self.name = name


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
    'storage_class': "Tes tStorageClass"
}

NOVA.servers.find = mock.MagicMock(return_value=DummyServer("node-1-test"))
NOVA.keypairs.get = mock.MagicMock(return_value='otiram')
NOVA.glance.find_image = mock.MagicMock(return_value='Ubuntu')
NOVA.flavors.find = mock.MagicMock(return_value='ECS.C1.4-8')
NEUTRON.find_resource = mock.MagicMock(return_value={'id': 'acedfr3c4223ee21'})
NEUTRON.create_port = mock.MagicMock(
    return_value={"port": {"admin_state_up": True,
                           "network_id": 'acedfr3c4223ee21',
                           "id": "abcdefg12345678",
                           "fixed_ips": [{"ip_address": "192.168.1.101"}]}})
NEUTRON.list_security_groups = mock.MagicMock(
    return_value=iter([{"security_groups": []}]))

NEUTRON.create_security_group = mock.MagicMock(
    return_value={"security_group": {'id':
                                     'e5d896d7-b2bc-4b0c-94ba-c542b4b8e49c'}})

NEUTRON.list_subnets = mock.MagicMock(
    return_value={'subnets': [{'id': 'e6d899d9-b1bc-4b1c-96ba-c541b4b8e49c'}]})


def test_node_builder():
    """ test the node builder class"""
    nb = NodeBuilder(NOVA, NEUTRON, CINDER, CONFIG)
    nodes = nb.get_nodes()

    assert isinstance(nodes[0], kolt.cloud.openstack.Instance)
    assert nodes[0].name == 'node-1-test'
