"""
cli.py
======

misc functions to interact with the cluster, usually called from
``kolt.kolt.Kolt``.

Don't use directly
"""
import asyncio
import sys

from kolt.util.hue import red, yellow  # pylint: disable=no-name-in-module
from kolt.cloud.openstack import delete_loadbalancer
from kolt.cloud import OpenStackAPI
from .util.util import get_kubeconfig_yaml, get_logger

LOGGER = get_logger(__name__)


def delete_cluster(config, nova, neutron, force=False):
    """
    completly delete a cluster from openstack.

    This function removes all compute instance, volume, loadbalancer,
    security groups rules and security groups
    """
    print(red("You are about to destroy your cluster '{}'!!!".format(
        config["cluster-name"])))

    if not force:
        print(red("Are you really sure ? [y/N]"))
        ans = input(red("ARE YOU REALLY SURE???"))
    else:
        ans = 'y'

    if ans.lower() == 'y':
        cluster_suffix = "-%s" % config['cluster-name']
        servers = [server for server in nova.servers.list() if
                   server.name.endswith(cluster_suffix)]

        async def del_server(server):
            await asyncio.sleep(1)
            nics = [nic for nic in server.interface_list()]
            server.delete()
            list(neutron.delete_port(nic.id) for nic in nics)
            print("deleted %s ..." % server.name)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(del_server(server)) for server in servers]

        if tasks:
            loop.run_until_complete(asyncio.wait(tasks))

        loop.close()
        delete_loadbalancer(neutron, config['cluster-name'])
        connection = OpenStackAPI.connect()
        secg = connection.list_security_groups(
            {"name": '%s-sec-group' % config['cluster-name']})
        if secg:
            for sg in secg:
                for rule in sg.security_group_rules:
                    connection.delete_security_group_rule(rule['id'])

                for port in connection.list_ports():
                    if sg.id in port.security_groups:
                        connection.delete_port(port.id)

        connection.delete_security_group(
            '%s-sec-group' % config['cluster-name'])

    else:
        sys.exit(1)


def write_kubeconfig(config, lb_address, admin_token,
                     write=False):
    """
    Write a kubeconfig file to the filesystem
    """
    path = None
    username = "admin"
    master_uri = "https://%s:6443" % lb_address
    kubeconfig = get_kubeconfig_yaml(
        master_uri, username, admin_token, write,
        encode=False, ca='certs-%s/ca.pem' % config['cluster-name'])
    if write:
        path = '-'.join((config['cluster-name'], 'admin.conf'))
        LOGGER.info(yellow("You can use your config with:"))
        LOGGER.info(yellow("kubectl get nodes --kubeconfig=%s" % path))
        with open(path, "w") as fh:
            fh.write(kubeconfig)

    return path
