import asyncio
import logging
import sys

from kolt.util.hue import red, yellow
from kolt.cloud.openstack import delete_loadbalancer
from kolt.cloud import OpenStackAPI
from .util.util import get_kubeconfig_yaml

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)


def delete_cluster(config, nova, neutron):
    print(red("You are about to destroy your cluster '{}'!!!".format(
          config["cluster-name"])))
    print(red("Are you really sure ? [y/N]"))
    ans = input(red("ARE YOU REALLY SURE???"))

    if ans.lower() == 'y':
        cluster_suffix = "-%s" % config['cluster-name']
        servers = [server for server in nova.servers.list() if
                   server.name.endswith(cluster_suffix)]

        async def del_server(server):
            await asyncio.sleep(1)
            nics = [nic for nic in server.interface_list()]
            server.delete()
            [neutron.delete_port(nic.id) for nic in nics]
            print("deleted %s ..." % server.name)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(del_server(server)) for server in servers]

        if tasks:
            loop.run_until_complete(asyncio.wait(tasks))
        loop.close()
        delete_loadbalancer(neutron, config['private_net'],
                            config['cluster-name'])
        connection = OpenStackAPI.connect()
        connection.delete_security_group(
            '%s-sec-group' % config['cluster-name'])

    else:
        sys.exit(1)


def write_kubeconfig(config, lb_address, admin_token,
                     write=False):

    username = "admin"
    master_uri = "https://%s:6443" % lb_address
    kubeconfig = get_kubeconfig_yaml(
        master_uri, username, admin_token, write,
        encode=False, ca='certs-%s/ca.pem' % config['cluster-name'])
    if write:
        path = '-'.join((config['cluster-name'], 'admin.conf'))
        logger.info(yellow("You can use your config with:"))
        logger.info(yellow("kubectl get nodes --kubeconfig=%s" % path))
        with open(path, "w") as f:
            f.write(kubeconfig)
        return path
