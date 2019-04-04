"""
koris
=====

The main entry point for the kubernetes cluster build.
Don't use it directly, instead install the package with setup.py.
It automatically creates an executable in your path.

"""
import argparse
import os
import shutil
import ssl
import sys
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import yaml


from mach import mach1

from koris.cloud.openstack import get_clients, OSCloudConfig
from koris.cloud.openstack import BuilderError, InstanceExists
from koris.util.util import KorisVersionCheck

from . import __version__
from .cli import delete_cluster
from .deploy.k8s import K8S

from .util.hue import red, info as infomsg  # pylint: disable=no-name-in-module
from .util.util import (get_logger, )

from .cloud.builder import ClusterBuilder, NodeBuilder, ControlPlaneBuilder
from .cloud.openstack import OSClusterInfo

# pylint: disable=protected-access
ssl._create_default_https_context = ssl._create_unverified_context

KORIS_DOC_URL = "https://pi.docs.noris.net/koris/"
LOGGER = get_logger(__name__)


def update_config(config_dict, config, amount, role='nodes'):
    """update the cluster configuration file"""
    key = "n-%s" % role
    config_dict[key] = config_dict[key] + amount
    updated_name = config.split(".")
    updated_name.insert(-1, "updated")
    updated_name = ".".join(updated_name)
    with open(updated_name, 'w') as stream:
        yaml.dump(config_dict, stream=stream)

    print(infomsg("An updated cluster configuration was written to: {}".format(
        updated_name)))


def add_node(cloud_config,
             os_cluster_info,
             role,
             zone,
             amount,
             flavor,
             k8s,
             config_dict):
    """the actual logic of adding a node"""
    node_builder = NodeBuilder(
        config_dict,
        os_cluster_info,
        cloud_config=cloud_config)

    tasks = node_builder.create_nodes_tasks(k8s.host,
                                            k8s.get_bootstrap_token(),
                                            k8s.ca_info,
                                            role=role,
                                            zone=zone,
                                            flavor=flavor,
                                            amount=amount)
    node_builder.launch_new_nodes(tasks)


@mach1()
class Koris:  # pylint: disable=no-self-use,too-many-locals
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

        try:
            html_string = str(urlopen(KORIS_DOC_URL, timeout=1.5).read())
        except (HTTPError, URLError):
            html_string = ""

        KorisVersionCheck(html_string).check_is_latest(__version__)

    def _get_version(self):
        print("%s version: %s" % (self.__class__.__name__, __version__))

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
        except InstanceExists:
            pass
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
        certs_location = 'certs-' + config['cluster-name']
        try:
            shutil.rmtree(certs_location)
        except FileNotFoundError:
            print(red("Certificates {} already deleted".format(certs_location)))
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
        ---
        Add a node to the current active context in your KUBECONFIG.
        You can specify any other configuration file by overriding the
        KUBECONFIG environment variable.
        """
        with open(config, 'r') as stream:
            config_dict = yaml.safe_load(stream)

        k8s = K8S(os.getenv("KUBECONFIG"))

        os_cluster_info = OSClusterInfo(self.nova, self.neutron, self.cinder,
                                        config_dict)
        try:
            subnet = self.neutron.find_resource('subnet', config_dict['subnet'])
        except KeyError:
            subnet = self.neutron.list_subnets()['subnets'][-1]

        cloud_config = OSCloudConfig(subnet['id'])

        if role == 'node':
            add_node(
                cloud_config, os_cluster_info, role, zone, amount, flavor, k8s,
                config_dict)
            update_config(config_dict, config, amount)

        elif role == 'master':
            k8s.validate_context(os_cluster_info.conn)
            builder = ControlPlaneBuilder(config_dict, os_cluster_info,
                                          cloud_config)
            master = builder.add_master(zone, flavor)

            try:
                k8s.launch_master_adder(master.name, master.ip_address)
            except ValueError as error:
                print(red("Error encoutered ... ", error))
                print(red("You may want to remove the newly created Openstack "
                          "instance manually..."))
                return

            # Since everything seems to be fine, update the local config
            update_config(config_dict, config, 1, role='masters')
        else:
            print("Unknown role")


def main():
    """
    run and execute koris
    """
    k = Koris()
    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
