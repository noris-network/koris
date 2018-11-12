"""
kolt
====

The main entry point for the kubernetes cluster build.
Don't use it directly, instead install the package with setup.py.
It automatically creates an executable in your path.

"""
import argparse
import sys
import yaml

import pkg_resources

from mach import mach1

from kolt.cloud.openstack import get_clients
from kolt.cloud.openstack import BuilderError
from .cli import delete_cluster

from .util.hue import red, yellow  # pylint: disable=no-name-in-module
from .util.util import (get_logger, )

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
                                 help="show version and exit",
                                 default=argparse.SUPPRESS)

    def _get_version(self):
        print("Kolt version:", __version__)

    def apply(self, config):
        """
        Bootstrap a Kubernetes cluster

        config - configuration file
        inventory - invetory file to write
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder(config)
        try:
            builder.run(config)
        except BuilderError as err:
            print(red("Error encoutered ... "))
            print(red(err))
            delete_cluster(config, self.nova, self.neutron,
                           True)

    def k8s(self, config):  # pylint: disable=no-self-use
        """
        Bootstrap a Kubernetes cluster (deprecated)

        config - configuration file
        inventory - invetory file to write
        """
        print(yellow("This subcommand is deprecated and will be removed soon ...")) # noqa
        print(yellow("Use `apply` instead."))
        self.apply(config)

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


def main():
    """
    run and execute kolt
    """
    k = Kolt()
    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
