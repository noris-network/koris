"""
mini integration test for creation and deletion of load balancer
in OpenStack
"""
# pylint: disable=invalid-name
import asyncio
import os

from koris.cloud import OpenStackAPI
from koris.cloud.builder import get_clients
from koris.cloud.openstack import LoadBalancer, OSNetwork, OSSubnet, OSRouter
from koris.deploy.dex import create_dex, create_oauth2

_, CLIENT, _ = get_clients()

lb_name = os.getenv('LOADBALANCER_NAME', 'test')
lb_name = lb_name.split('-lb')[0]
config = {
    'cluster-name': lb_name,
    'private_net': {
        'name': 'koris-test-net',
        'subnet': {
            'name': 'test-subnet',
            'cidr': '192.168.0.0/16'
        }
    },
    'loadbalancer': {
        'floatingip': False
    }
}

CONN = OpenStackAPI.connect()
NET = OSNetwork(config, CONN).get_or_create()
SUBNET = OSSubnet(CLIENT, NET['id'], config).get_or_create()
OSRouter(CLIENT, NET['id'], SUBNET, config).get_or_create()
LB = LoadBalancer(config, CONN)


def create_and_configure():
    """
    create and configure a load-balancer in oneshot, in real life
    we postpone the configuration to a later stage.
    """

    loop = asyncio.get_event_loop()
    LB.create()

    master_ips = ['192.168.0.103', '192.168.0.104', '192.168.0.105']
    node_ips = ['192.168.0.120', '192.168.0.121']

    configure_lb_task = loop.create_task(LB.configure(master_ips))

    #  Dex testing
    print("Configuring the LoadBalancer for Dex ...")
    dex_task = loop.create_task(create_dex(LB, members=master_ips))
    oauth_task = loop.create_task(create_oauth2(LB, members=node_ips))

    tasks = [configure_lb_task, dex_task, oauth_task]

    loop.run_until_complete(asyncio.gather(*tasks))


if __name__ == '__main__':
    import sys
    actions = ['create', 'destroy', 'all']
    action = None
    if len(sys.argv) > 1:
        try:
            action = actions.index(sys.argv[1])
        except ValueError:
            pass
    if action == 0:
        create_and_configure()
        sys.exit(0)
    if action == 1:
        LB.delete()
        sys.exit(0)
    if action == 2:
        create_and_configure()
        LB.delete()
        sys.exit(0)
    else:
        print("You must run this script with an action")
        print("Action must be one of: {}".format(', '.join(actions)))
