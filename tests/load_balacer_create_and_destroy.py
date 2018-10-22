"""
mini integration test for creation and deletion of load balancer
in OpenStack
"""

import asyncio
from kolt.cloud.builder import get_clients
from kolt.cloud.openstack import (delete_loadbalancer, create_loadbalancer,
                                  configure_lb)
_, CLIENT, _ = get_clients()


def create_and_configure(name):
    """
    create and configure a load-balancer in oneshot, in real life
    we postpone the configuration to a later stage.
    """
    loop = asyncio.get_event_loop()
    lb, _ = create_loadbalancer(
        CLIENT,
        'test',
    )

    master_ips = ['192.168.0.103', '192.168.0.104', '192.168.0.105']

    configure_lb_task = loop.create_task(
        configure_lb(CLIENT, lb, name, master_ips))

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
        create_and_configure('test')
        sys.exit(0)
    if action == 1:
        delete_loadbalancer(CLIENT, 'test')
        sys.exit(0)
    if action == 2:
        create_and_configure('test')
        delete_loadbalancer(CLIENT, 'test')
        sys.exit(0)
    else:
        print("You must run this script with an action")
        print("Action must be one of: {}".format(', '.join(actions)))
