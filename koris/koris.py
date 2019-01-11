"""
koris
=====

The main entry point for the kubernetes cluster build.
Don't use it directly, instead install the package with setup.py.
It automatically creates an executable in your path.

"""
import argparse
import os
import sys
import yaml

from mach import mach1

from koris.cloud.openstack import get_clients
from koris.cloud.openstack import BuilderError
from . import __version__
from .cli import delete_cluster
from .deploy.k8s import K8S

from .util.hue import red  # pylint: disable=no-name-in-module
from .util.util import (get_logger, )

from .cloud.builder import ClusterBuilder, NodeBuilder

LOGGER = get_logger(__name__)


@mach1()
class Koris:  # pylint: disable=no-self-use
    """
    The main entry point for the program. This class does the CLI parsing
    and descides which action shoud be taken
    """
    def __init__(self):

        nova, neutron, cinder = get_clients()
        self.nova = nova
        self.neutron = neutron
        self.cinder = cinder
        self.parser.add_argument(  # pylint: disable=no-member
            "--version", action="store_true",
            help="show version and exit",
            default=argparse.SUPPRESS)

    def _get_version(self):  # pylint: disable=no-self-use
        print("Kolt version:", __version__)

    def apply(self, config):
        """
        Bootstrap a Kubernetes cluster

        config - configuration file
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder(config)
        try:
            builder.run(config)
        except BuilderError as err:
            print(red("Error encoutered ... "))
            print(red(err))
            delete_cluster(config, self.nova, self.neutron, self.cinder,
                           True)

    def destroy(self, config: str, force: bool = False):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        print(red(
            "You are about to destroy your cluster '{}'!!!".format(
                config['cluster-name'])))

        delete_cluster(config, self.nova, self.neutron, self.cinder, force)
        sys.exit(0)

    def add(self, config: str, flavor: str, zone: str,
            role: str = 'node', amount: int = 1):
        """
        Add a worker node or master node to the cluster.

        config - configuration file
        flavor - the machine flavor
        role - one of node or master
        amount - the number of worker nodes to add (masters are not supported)
        zone - the availablity zone
        """
        k8s_config_path = os.getenv("KUBECONFIG")
        k8s = K8S(k8s_config_path)

        # this is now implemented
        token = k8s.get_bootstrap_token()
        # implement discovery hash here

        NodeBuilder.create_nodes_tasks(config,
                                       flavor,
                                       zone,
                                       role,
                                       k8s.ca_cert,
                                       token,
                                       k8s.discovery_hash,
                                       amount=amount)


def main():
    """
    run and execute koris
    """
    k = Koris()
    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
