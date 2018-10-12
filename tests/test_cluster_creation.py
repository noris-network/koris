from unittest import mock

nova = mock.Mock()
neutron = mock.Mock()
nova.keypairs.get = mock.MagicMock(return_value='otiram')
nova.glance.find_image = mock.MagicMock(return_value='Ubuntu')
nova.flavors.find = mock.MagicMock(return_value='ECS.C1.4-8')
neutron.find_resource = mock.MagicMock(return_value={'id': 'acedfr3c4223ee21'})
neutron.create_port = mock.MagicMock(
    return_value={"port": {"admin_state_up": True,
                           "network_id": 'acedfr3c4223ee21',
                           "id": "abcdefg12345678",
                           "fixed_ips": [{"ip_address": "192.168.1.101"}]}})

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
    pass
