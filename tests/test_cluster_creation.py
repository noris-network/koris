import asyncio
from unittest import mock

from kolt.kolt import create_nodes

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

    hosts = {}
    tasks = create_nodes(nova, neutron, config, hosts)

    hosts_names = next(tasks)
    assert hosts_names == ['node-1-test', 'node-2-test', 'node-3-test']

    ips = list(next(tasks))

    # this is ugly, but for now works for us. Don't get the illusion
    # all port have the same IP! It's only so because are mock object is
    # bad
    # This can be improved ...
    assert ips == ['192.168.1.101'] * 3
    loop = asyncio.get_event_loop()
