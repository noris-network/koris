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
from .util.logger import Logger
from .cloud.builder import ClusterBuilder, NodeBuilder, ControlPlaneBuilder
from .cloud.openstack import (OSCloudConfig, BuilderError, InstanceExists,
                              delete_instance, OSClusterInfo, get_connection,
                              LoadBalancer, get_clients, InstanceNotFound)

# pylint: disable=protected-access
ssl._create_default_https_context = ssl._create_unverified_context

KORIS_DOC_URL = "https://pi.docs.noris.net/koris/"
LOGGER = Logger(__name__)


def update_config(config_dict, config, amount, role='nodes'):
    """update the cluster configuration file"""
    key = "n-%s" % role
    config_dict[key] = config_dict[key] + amount
    updated_name = config.split(".")
    updated_name.insert(-1, "updated")
    updated_name = ".".join(updated_name)
    with open(updated_name, 'w') as stream:
        yaml.dump(config_dict, stream=stream)

    LOGGER.success(("An updated cluster configuration was written to: "
                    f"{updated_name}"))


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


# pylint: disable=too-many-locals
def add_master(bootstrap_only, builder, zone, flavor, config, config_dict,
               os_cluster_info, k8s):
    """Add a new master to OpenStack and the Kubernetes cluster.

    Will add a new node to OpenStack, adjust the config, bootstrap the master
    and add the IP to the LoadBalancer pool.

    Args:
        bootstrap_only (list): A list of name and IP for the node to be
            bootstrapped
         builder (:class:`.cloud.openstack.ControlPlaneBuilder`): A
            ControlPlanBuilder instance.
        zone (str): The AZ to add the new node in.
        flavor (str): The node flavor of the node.
        config (str): The path of the koris config.
        config_dict (dict): The parsed koris config.
        os_cluster_info (:class:`.cloud.openstack.OSClusterInfo`): A
            OSClusterInfo instance.
        k8s (:class:`.deploy.K8S`): A K8S instance.
    """

    if not bootstrap_only:
        master = builder.add_master(zone, flavor)
        name, ip_address = master.name, master.ip_address
        update_config(config_dict, config, 1, role='masters')

    try:
        k8s.bootstrap_master(name, ip_address)
    except ValueError as err:
        LOGGER.error(f"Error: {err}")

        # Cleanup
        LOGGER.info("Deleting instance %s from OpenStack ...", name)
        delete_instance(name, os_cluster_info.conn)

        sys.exit(1)
    except urllib3.exceptions.MaxRetryError:
        LOGGER.error(("Connection failed! Are you using the correct "
                      "kubernetes context?"))
        sys.exit(1)

    # Adding master to LB
    conn = get_connection()
    lb = LoadBalancer(config_dict, conn)
    if not lb.get():
        LOGGER.error("No LoadBalancer found")
        sys.exit(1)
    try:
        master_pool = lb.master_listener['pool']['id']
    except KeyError as exc:
        LOGGER.error(f"Unable to obtain master-pool: {exc}")
        sys.exit(1)
    LOGGER.info("Adding new master to LoadBalancer ...")
    lb.add_member(master_pool, master.ip_address)


# pylint: disable=no-member
def delete_node(config_dict, name):
    """Delete a master or worker node from the cluster.

    Will perform basic validity checks on the name.

    Args:
        config_dict (dict): A dictionary representing the config.
        name (str): The name of the node to delete.
        conn: An OpenStack connection object.

    Raises:
        ValueError if name is invalid or resources are not found.
    """

    if not name or name is None:
        raise ValueError("name can't be empty")

    conn = get_connection()

    # Get our LoadBalancer
    lb = LoadBalancer(config_dict, conn)
    lbinst = lb.get()
    if not lbinst:
        raise ValueError("no LoadBalancer found")

    k8s = K8S(os.getenv("KUBECONFIG"))

    # Verify we are in the project of our target cluster
    if not k8s.validate_context(conn):
        raise ValueError("cluster not part of your sourced OpenStack tenant")

    # Drain the node first
    k8s.drain_node(name)

    # If master, remove member from etcd cluster and LoadBalancer
    if 'master' in name:
        k8s.remove_from_etcd(name)

        # Get IP of node to be deleted
        srv = conn.compute.find_server(name)
        if not srv:
            raise ValueError(f"instance '{name}' not found")
        ip = list(conn.compute.server_ips(srv))
        if not ip:
            raise ValueError(f"instance '{name}' has no IP")

        # Get member ID of node to be ledeted
        mems = lb.master_listener['pool']['members']
        mem_id = [x['id'] for x in mems if x['address'] == ip[0].address]
        if mem_id:
            # Delete member from LoadBalancer master pool
            pool_id = lb.master_listener['pool']['id']
            lb.del_member(mem_id[0], pool_id)
            LOGGER.success("Removed instance '%s' from LoadBalancer '%s'", name,
                           lb.name)
        else:
            LOGGER.debug("Members: %s", mems)
            LOGGER.error("instance '%s' not part of LoadBalancer", name)
    # Delete the node from Kubernetes
    k8s.delete_node(name)

    # Delete the instance from OpenStack
    delete_instance(name, conn, ignore_not_found=False)


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

        verbosity_help = "".join([
            "set the verbosity level (",
            "0 = quiet, ",
            "1 = error, ",
            "2 = warning, ",
            "3 = info, ",
            "4 = debug)"])
        self.parser.add_argument("--verbosity",  # pylint: disable=no-member
                                 "-v",
                                 help=verbosity_help,
                                 choices=['0', '1', '2', '3', '4', 'quiet',
                                          'error', 'warning', 'info', 'debug'],
                                 type=str,
                                 default=3)

        try:
            html_string = str(urlopen(KORIS_DOC_URL, timeout=1.5).read())
        except (HTTPError, URLError):
            html_string = ""

        KorisVersionCheck(html_string).check_is_latest(__version__)

    def _get_version(self):
        print("%s version: %s" % (self.__class__.__name__, __version__))

    def _get_verbosity(self):
        pass

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
            LOGGER.error(f"Error: {err}")
            delete_cluster(config, nova, neutron, cinder,
                           True)

    def destroy(self, config: str, force: bool = False):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        nova, neutron, cinder = get_clients()

        LOGGER.question(
            "Deleting cluster '{}'".format(
                config['cluster-name']))

        delete_cluster(config, nova, neutron, cinder, force)
        certs_location = 'certs-' + config['cluster-name']
        try:
            shutil.rmtree(certs_location)
        except FileNotFoundError:
            LOGGER.warn(f"Certificates {certs_location} already deleted")
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
            LOGGER.error('Error: resource must be '
                         '[%s]' % " | ".join(allowed_resource))
            sys.exit(1)

        if resource == "node":
            if not name or name is None:
                LOGGER.error("Must specifiy --name when deleting a node")
                sys.exit(1)

            change_config = True
            try:
                delete_node(config_dict, name)
            except (ValueError) as exc:
                LOGGER.error(f"Error: {exc}")
                sys.exit(1)
            except InstanceNotFound:
                change_config = False

            # Don't change config if Instance wasn't deleted from OpenStack
            if change_config:
                if "master" in name:
                    update_config(config_dict, config, -1, "masters")
                else:
                    update_config(config_dict, config, -1, "nodes")

        else:
            LOGGER.error("Feature not implemented yet."
                         "Please use 'koris destroy' for time being!")

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
                LOGGER.error(("To bootstrap a node you must specify both"
                              "name and IP"))
                sys.exit(1)

            LOGGER.info(("Bootstraping host {} with address {}, "
                         "assuming it's present".format(name, ip_address)))

        elif len(list(filter(None, [flavor, zone]))) < 2:
            LOGGER.error(("You  must specify both flavor and zone if you want"
                          "to create an instance"))
            sys.exit(1)

        with open(config, 'r') as stream:
            config_dict = yaml.safe_load(stream)

        nova, neutron, cinder = get_clients()

        k8s = K8S(os.getenv("KUBECONFIG"))
        os_cluster_info = OSClusterInfo(nova, neutron, cinder,
                                        config_dict)

        if not k8s.validate_context(os_cluster_info.conn):
            LOGGER.error(("Error: cluster not part of your sourced"
                          "OpenStack tenant"))
            sys.exit(1)

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
            builder = ControlPlaneBuilder(config_dict, os_cluster_info,
                                          cloud_config)
            try:
                add_master(bootstrap_only, builder, zone, flavor, config,
                           config_dict, os_cluster_info, k8s)
            except (RuntimeError, ValueError) as exc:
                LOGGER.error(f"Error: {exc}")
                sys.exit(1)

        else:
            LOGGER.warn("Unknown role")

        LOGGER.success("Adding new node finished successfully")


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

    # Setting verbosity level
    level = k.parser.parse_args().verbosity
    level_to_int = {
        'quiet': 0,
        'error': 1,
        'warning': 2,
        'info': 3,
        'debug': 4}
    try:
        LOGGER.level = int(level)
    except ValueError:
        LOGGER.level = level_to_int[level]

    # pylint misses the fact that Kolt is decorater with mach.
    # the mach decortaor analyzes the methods in the class and dynamically
    # creates the CLI parser. It also adds the method run to the class.
    k.run()  # pylint: disable=no-member
