"""
A small script to test instance creation on OpenStack
"""

import asyncio
import sys


from koris.cloud.openstack import Instance, get_clients, get_or_create_sec_group

CONFIG = {'zone': 'de-nbg6-1a',
          'class': 'PI-Storage-Class',
          'flavor': 'ECS.C1.1-2',
          'image': "Ubuntu Xenial Server Cloudimg",
          'secgroup': 'default',
          'keypair': sys.argv[1]}


NOVA, NEUTRON, CINDER = get_clients()
net = NEUTRON.find_resource("network", sys.argv[2])  # noqa

secgroup = get_or_create_sec_group(NEUTRON, CONFIG['secgroup'])

secgroups = [secgroup['id']]

instance = Instance(CINDER, NOVA, 'tiny-test', net, 'de-nbg6-1a',
                    'dummy',
                    {'class': "PI-Storage-Class",
                     'image': NOVA.glance.find_image(CONFIG['image'])})

keypair = NOVA.keypairs.get(CONFIG['keypair'])

instance.attach_port(NEUTRON, net, secgroups)


loop = asyncio.get_event_loop()

task = loop.create_task(
    instance.create(NOVA.flavors.find(name=CONFIG['flavor']),
                    secgroups,
                    keypair,
                    ""
                    ))

loop.run_until_complete(asyncio.gather(*[task]))

task = instance.delete(NEUTRON)

loop.run_until_complete(asyncio.gather(*[task]))
