from unittest import mock
from kolt.util import NodeZoneNic, OSClusterInfo

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


def test_osclusterinfo():

    info = OSClusterInfo(nova, neutron, config)

    assert info.nodes_names == ['node-1-test', 'node-2-test', 'node-3-test']

    args = list(info.node_args_builder("generic_user_data"))

    assert args == [
        'ECS.C1.4-8', 'Ubuntu', 'otiram',
        ['acedfr3c4223ee21'], 'node', 'generic_user_data']

    nodes_zones = info.distribute_nodes()

    assert nodes_zones[0].name == "node-1-test"
    assert nodes_zones[0].zone == "nbg6-1a"
    assert nodes_zones[1].name == "node-2-test"
    assert nodes_zones[1].zone == "nbg6-1a"
    assert nodes_zones[2].name == "node-3-test"
    assert nodes_zones[2].zone == "nbg6-1b"

    # TODO: add test for assign_nics_to_nodes
    nics = {

    }
