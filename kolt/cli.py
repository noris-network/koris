"""
cli.py
======

misc functions to interact with the cluster, usually called from
``kolt.kolt.Kolt``.

Don't use directly
"""
import sys

from kolt.util.hue import red, yellow  # pylint: disable=no-name-in-module
from kolt.cloud.openstack import remove_cluster
from .util.util import get_kubeconfig_yaml, get_logger

LOGGER = get_logger(__name__)


def delete_cluster(config, nova, neutron, force=False):
    """
    completly delete a cluster from openstack.

    This function removes all compute instance, volume, loadbalancer,
    security groups rules and security groups
    """
    if not force:
        print(red("Are you really sure ? [y/N]"))
        ans = input(red("ARE YOU REALLY SURE???"))
    else:
        ans = 'y'

    if ans.lower() == 'y':
        remove_cluster(config, nova, neutron)
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
