"""
A small script to test instance creation on OpenStack
"""

import asyncio
import sys


from kolt.cloud.openstack import Instance, get_clients, get_or_create_sec_group

CONFIG = {'zone': 'de-nbg6-1a',
          'class': 'PI-Storage-Class',
          'flavor': 'ECS.C1.1-2',
          'image': "Ubuntu Xenial Server Cloudimg",
          'secgroup': 'default',
          'keypair': sys.argv[1]}


NOVA, NEUTRON, CINDER = get_clients()

secgroup = get_or_create_sec_group(NEUTRON, CONFIG['secgroup'])

secgroups = [secgroup['id']]

instance = Instance(CINDER, NOVA, 'tiny-test', 'de-nbg6-1a',
                    {'class': "PI-Storage-Class",
                     'image': NOVA.glance.find_image(CONFIG['image'])})

keypair = NOVA.keypairs.get(CONFIG['keypair'])

loop = asyncio.get_event_loop()

task = loop.create_task(
    instance.create(NOVA.flavors.find(name=CONFIG['flavor']),
                    secgroups,
                    keypair,
                    ""
                    ))

loop.run_until_complete(asyncio.gather(*[task]))
