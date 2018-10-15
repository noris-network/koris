"""
kolt
====

The main entry point for the kubernetes cluster build.
Don't use it directly, instead install the package with setup.py.
It automatically creates an executable in your path.

"""
import sys
import yaml

import pkg_resources

from mach import mach1

from kolt.cloud.openstack import get_clients
from kolt.cloud.openstack import BuilderError
from .cli import delete_cluster
from .ssl import create_certs

from .util.hue import red, info  # pylint: disable=no-name-in-module
from .ssl import CertBundle
from .util.util import (get_logger,
                        get_server_info_from_openstack,
                        )

from .cloud.builder import ClusterBuilder

LOGGER = get_logger(__name__)


__version__ = pkg_resources.get_distribution('kolt').version


@mach1()
class Kolt:
    """
    The main entry point for the program. This class does the CLI parsing
    and descides which action shoud be taken
    """
    def __init__(self):

        nova, neutron, cinder = get_clients()
        self.nova = nova
        self.neutron = neutron
        self.cinder = cinder
        self.parser.add_argument("--version", action="store_true",
                                 help="show version and exit")

    def _get_version(self):
        print("Kolt version:", __version__)

    def certs(self, config, key=None, ca=None):  # pylint: disable=invalid-name
        """
        Create cluster certificates
        """
        if key and ca:
            ca_bundle = CertBundle.read_bundle(key, ca)
        else:
            ca_bundle = None

        names, ips = get_server_info_from_openstack(config, self.nova)
        create_certs(config, names, ips, ca_bundle=ca_bundle)

    def k8s(self, config):  # pylint: disable=no-self-use
        """
        Bootstrap a Kubernetes cluster

        config - configuration file
        inventory - invetory file to write
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        try:
            builder.run(config)
        except BuilderError as err:
            print(red("Error encoutered ... "))
            print(red(err))
            delete_cluster(config['cluster-name'], self.nova, self.neutron,
                           True)

    def kubespray(self, config, inventory=None):  # pylint: disable=no-self-use
        """
        Launch machines on opentack and write a configuration for kubespray
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        cfg = builder.run(config, no_cloud_init=True)

        if inventory:
            with open(inventory, 'w') as fh:
                cfg.write(fh)
        else:
            print(info("Here is your inventory ..."))
            print(
                red(
                    "You can save this inventory to a file with the option -i"))  # noqa
            cfg.write(sys.stdout)

    def destroy(self, config: str, force: bool = False):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        print(red(
            "You are about to destroy your cluster '{}'!!!".format(
                config['cluster-name'])))

        delete_cluster(config["cluster-name"], self.nova, self.neutron, force)
        sys.exit(0)


def main():
    """
    run and execute kolt
    """
    k = Kolt()
    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
