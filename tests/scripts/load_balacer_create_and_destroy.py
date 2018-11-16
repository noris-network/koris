"""
mini integration test for creation and deletion of load balancer
in OpenStack
"""

import asyncio
import os

from koris.cloud.builder import get_clients
from koris.cloud.openstack import LoadBalancer
_, CLIENT, _ = get_clients()


config = {'cluster-name': os.getenv('LOADBALANCER_NAME', 'test')}

LB = LoadBalancer(config)


def create_and_configure():
    """
    create and configure a load-balancer in oneshot, in real life
    we postpone the configuration to a later stage.
    """
    loop = asyncio.get_event_loop()
    lb, _ = LB.create(CLIENT)

    master_ips = ['192.168.0.103', '192.168.0.104', '192.168.0.105']

    configure_lb_task = loop.create_task(LB.configure(CLIENT, master_ips))

    tasks = [configure_lb_task]

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
        LB.delete(CLIENT)
        sys.exit(0)
    if action == 2:
        create_and_configure()
        LB.delete(CLIENT)
        sys.exit(0)
    else:
        print("You must run this script with an action")
        print("Action must be one of: {}".format(', '.join(actions)))
