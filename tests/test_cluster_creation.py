from unittest import mock

from kolt.kolt import create_nodes

nova = mock.Mock()
neutron = mock.Mock()
nova.keypairs.get = mock.MagicMock(return_value='otiram')
nova.glance.find_image = mock.MagicMock(return_value='Ubuntu')
nova.flavors.find = mock.MagicMock(return_value='ECS.C1.4-8')
neutron.find_resource = mock.MagicMock(return_value={'id': 'acedfr3c4223ee21'})


config = {
    "n-nodes": 3,
    "n-masters": 3,
    "keypair": "otiram",
    "availibility-zones": ['nbg6-1a', 'nbg6-1b'],
    "cluster-name": "test",
    "private_net": "test-net",
    "security_group": "test-group",
    "image": "ubuntu 16.04",
    "node_flavor": "ECS.C1.4-8"
}


def test_create_nodes():
    hosts = {}
    tasks = create_nodes(nova, neutron, config, hosts)
    # TODO: finish this test
