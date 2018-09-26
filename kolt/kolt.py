# https://support.ultimum.io/support/solutions/articles/1000125460-python-novaclient-neutronclient-glanceclient-swiftclient-heatclient
# http://docs.openstack.org/developer/python-novaclient/ref/v2/servers.html
import sys

import yaml


from mach import mach1

from .cli import delete_cluster
from .ssl import create_certs
from kolt.cloud.openstack import get_clients

from .util.hue import red, info
from .ssl import CertBundle
from .util.util import (get_logger,
                        get_server_info_from_openstack,
                        )

from .cloud.builder import ClusterBuilder

logger = get_logger(__name__)


@mach1()
class Kolt:

    def __init__(self):

        global nova, neutron, cinder
        nova, neutron, cinder = get_clients()

    def certs(self, config, key=None, ca=None):
        """
        Create cluster certificates
        """
        if key and ca:
            ca_bundle = CertBundle.read_bundle(key, ca)
        else:
            ca_bundle = None

        names, ips = get_server_info_from_openstack(config, nova)
        create_certs(config, names, ips, ca_bundle=ca_bundle)

    def k8s(self, config):
        """
        Bootstrap a Kubernetes cluster

        config - configuration file
        inventory - invetory file to write
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        builder.run(config)

    def kubespray(self, config, inventory=None):
        """
        Launch machines on opentack and write a configuration for kubespray
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        cfg = builder.run(config, no_cloud_init=True)

        if inventory:
            with open(inventory, 'w') as f:
                cfg.write(f)
        else:
            print(info("Here is your inventory ..."))
            print(
                red(
                    "You can save this inventory to a file with the option -i"))  # noqa
            cfg.write(sys.stdout)

    def destroy(self, config):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        delete_cluster(config, nova, neutron)
        sys.exit(0)


def main():
    k = Kolt()
    k.run()
