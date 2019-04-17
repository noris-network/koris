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
import urllib3
import yaml


from mach import mach1

from koris.util.util import KorisVersionCheck

from . import __version__
from .cli import delete_cluster
from .deploy.k8s import K8S

from .util.hue import red, info as infomsg  # pylint: disable=no-name-in-module
from .util.util import (get_logger, )

from .cloud.builder import ClusterBuilder, NodeBuilder, ControlPlaneBuilder
from .cloud.openstack import (OSCloudConfig, BuilderError, InstanceExists,
                              delete_instance, OSClusterInfo, get_connection,
                              LoadBalancer, get_clients)

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
    """Create a new host(s) in OpenStack which will join the cluster as a node(s)

    This hosts boots with all paramerters required for it to join the cluster
    with a cloud-init.

    Args:
        cloud_config (``koris.cloud.openstack.OSClusterInfo``): the content
           cloud.conf file
        os_cluster_info (``koris.cloud.openstack.OSClusterInfo``)
        role (str): the host role currently only "node" is supported here.
        zone (str): the AZ in OpenStack in which the hosts are created
        amount (int): the number of instance to create
        flavour (str): the flavor in OpenStack to create
        k8s (``koris.deploy.K8S``): an instance which creates a bootstrap token.
        config_dict (dict): the koris configuration yaml as ``dict``

    """
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


def delete_node(name):
    """Delete a master or worker node from the cluster.

    Will perform basic validity checks on the name.

    Args:
        name (str): The name of the node to delete.
        conn: An OpenStack connection object.

    Raises:
        ValueError if name is invalid.
    """

    if not name or name is None:
        raise ValueError("name can't be empty")

    conn = get_connection()

    k8s = K8S(os.getenv("KUBECONFIG"))

    # Drain the node first
    k8s.drain_node(name)

    # If master, remove member from etcd cluster
    if 'master' in name:
        k8s.remove_from_etcd(name)

    # Delete the node from Kubernetes
    k8s.delete_node(name)

    # Delete the instance from OpenStack
    delete_instance(name, conn)


@mach1()
class Koris:  # pylint: disable=no-self-use,too-many-locals
    """
    The main entry point for the program. This class does the CLI parsing
    and descides which action shoud be taken
    """
    def __init__(self):
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

        nova, neutron, cinder = get_clients()

        builder = ClusterBuilder(config)
        try:
            builder.run(config)
        except InstanceExists:
            pass
        except BuilderError as err:
            print(red("Error encoutered ... "))
            print(red(err))
            delete_cluster(config, nova, neutron, cinder,
                           True)

    def destroy(self, config: str, force: bool = False):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        nova, neutron, cinder = get_clients()

        print(red(
            "You are about to destroy your cluster '{}'!!!".format(
                config['cluster-name'])))

        delete_cluster(config, nova, neutron, cinder, force)
        certs_location = 'certs-' + config['cluster-name']
        try:
            shutil.rmtree(certs_location)
        except FileNotFoundError:
            print(red("Certificates {} already deleted".format(certs_location)))
        sys.exit(0)

    def delete(self, config: str, resource: str, name: str = ""):
        """
        Delete a node from the cluster, or the complete cluster.

        config - koris configuration file.
        resource - the type of resource to delete. [node | cluster]
        name - the name of the resource to delete.
        """

        with open(config, 'r') as stream:
            config_dict = yaml.safe_load(stream)

        allowed_resource = ["node", "cluster"]
        if resource not in allowed_resource:
            msg = f'Error: resource must be [{" | ".join(allowed_resource)}]'
            print(red(msg))
            sys.exit(1)

        if resource == "node":
            if not name or name is None:
                LOGGER.error("Must specifiy --name when deleting a node")
                sys.exit(1)

            try:
                delete_node(name)
            except (ValueError) as exc:
                LOGGER.error("Error: %s", exc)
                sys.exit(1)

            if "master" in name:
                update_config(config_dict, config, -1, "masters")
            else:
                update_config(config_dict, config, -1, "nodes")

        else:
            msg = " ".join([
                "Feature not implemented yet.",
                "Please use 'koris destroy' for time being!"
            ])
            print(red(msg))

    # pylint: disable=too-many-statements
    def add(self, config: str, flavor: str = None, zone: str = None,
            role: str = 'node', amount: int = 1, ip_address: str = None,
            name: str = None):
        """
        Add a worker node or master node to the cluster.

        config - configuration file
        flavor - the machine flavor
        zone - the availablity zone
        role - one of node or master
        amount - the number of worker nodes to add (masters are not supported)
        address - the IP address of the host to bootstrap
        hostname - the hostname to bootstrap
        ---
        Add a node or a master to the current active context in your KUBECONFIG.
        You can specify any other configuration file by overriding the
        KUBECONFIG environment variable.
        If you specify a name and IP address the program will only try to join
        it to the cluster without trying to create the host in the cloud first.
        """
        bootstrap_only = list(filter(None, [name, ip_address]))

        if bootstrap_only:
            if len(bootstrap_only) != 2:
                print("To bootstrap a node you must specify both name and IP")
                sys.exit(1)

            print(
                "Bootstraping host {} with address {}, "
                "assuming it's present".format(name, ip_address))

        elif len(list(filter(None, [flavor, zone]))) < 2:
            print("You  must specify both flavor and zone if you want to create"
                  " an instance")
            sys.exit(1)

        with open(config, 'r') as stream:
            config_dict = yaml.safe_load(stream)

        nova, neutron, cinder = get_clients()

        k8s = K8S(os.getenv("KUBECONFIG"))
        os_cluster_info = OSClusterInfo(nova, neutron, cinder,
                                        config_dict)
        k8s.validate_context(os_cluster_info.conn)

        try:
            subnet = neutron.find_resource(
                'subnet', config_dict['private_net']['subnet']['name'])
        except KeyError:
            subnet = neutron.list_subnets()['subnets'][-1]

        cloud_config = OSCloudConfig(subnet['id'])
        if role == 'node':
            add_node(
                cloud_config, os_cluster_info, role, zone, amount, flavor, k8s,
                config_dict)
            # Since everything seems to be fine, update the local config
            update_config(config_dict, config, amount)

        elif role == 'master':
            if not bootstrap_only:
                builder = ControlPlaneBuilder(config_dict, os_cluster_info,
                                              cloud_config)
                master = builder.add_master(zone, flavor)
                name, ip_address = master.name, master.ip_address
                update_config(config_dict, config, 1, role='masters')

            try:
                k8s.bootstrap_master(name, ip_address)
            except ValueError as error:
                print(red("Error encoutered ... ", error))
                print(red("You may want to remove the newly created Openstack "
                          "instance manually..."))
                sys.exit(1)
            except urllib3.exceptions.MaxRetryError:
                LOGGER.warning(
                    red("Connection failed! Are you using the correct "
                        "kubernetes context?"))
                sys.exit(1)

            # Adding master to LB
            conn = get_connection()
            lb = LoadBalancer(config_dict, conn)
            lbinst = lb.get()
            if not lbinst:
                red("No LoadBalancer found")
                sys.exit(1)
            try:
                master_pool = lb.master_listener['pool']['id']
            except KeyError as exc:
                red(f"Unable to obtain master-pool: {exc}")
                sys.exit(1)
            lb.add_member(master_pool, master.ip_address)

        else:
            print("Unknown role")


def main():
    """
    run and execute koris
    """
    k = Koris()

    # Display a little information message, at the koris --help page.
    # pylint: disable=no-member
    k.parser.description = 'Before any koris command can be run, an '\
                           'OpenStack RC file has to be sourced in the '\
                           'shell. See online documentation for more '\
                           'information.'

    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
