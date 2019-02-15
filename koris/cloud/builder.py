"""
Builder
=======

Build a kubernetes cluster on a cloud
"""
import asyncio
import random
import string
import sys
import time
import urllib

from koris.cli import write_kubeconfig
from koris.deploy.k8s import K8S
from koris.deploy.dex import Dex
from koris.provision.cloud_init import FirstMasterInit, NthMasterInit, NodeInit
from koris.ssl import create_key, create_ca, CertBundle
from koris.ssl import discovery_hash as get_discovery_hash
from koris.util.hue import (  # pylint: disable=no-name-in-module
    red, info, lightcyan as cyan)

from koris.util.util import get_logger
from .openstack import OSClusterInfo, InstanceExists
from .openstack import (get_clients, Instance,
                        OSCloudConfig, LoadBalancer,
                        )

LOGGER = get_logger(__name__)

NOVA, NEUTRON, CINDER = get_clients()


def get_server_range(servers, cluster_name, role, amount):
    """
    Given a list of servers find the last server name and add N more
    """
    servers = [s for s in servers if
               s.name.endswith(cluster_name)]
    servers = [s for s in servers if s.name.startswith(role)]

    lastname = sorted(servers, key=lambda x: x.name)[-1].name
    idx = int(lastname.split('-')[1])
    return range(idx + 1, idx + amount + 1)


class NodeBuilder:
    """
    Interact with openstack and create a virtual machines with a volume,
    and network interface. The machines are provisioned with cloud-init.

    Args:
        config (dict) - the parsed configuration file
        osinfo (OSClusterInfo) - information about the currect cluster
        cloud_config (OSCloudConfig) - the cloud config generator
    """
    def __init__(self, config, osinfo, cloud_config=None):
        LOGGER.info(info(cyan(
            "gathering node information from openstack ...")))
        self.config = config
        self._info = osinfo
        self.cloud_config = cloud_config

    def create_new_nodes(self,
                         role='node',
                         zone=None,
                         flavor=None,
                         amount=1):
        """
        add additional nodes
        """
        nodes = [Instance(self._info.storage_client,
                          self._info.compute_client,
                          '%s-%d-%s' % (role, n, self.config['cluster-name']),
                          self._info.net,
                          zone,
                          role,
                          {'image': self._info.image,
                           'class': self._info.storage_class},
                          flavor
                          ) for n in
                 get_server_range(self._info.compute_client.servers.list(),
                                  self.config['cluster-name'],
                                  role,
                                  amount)]
        for node in nodes:
            node.attach_port(self._info.netclient, self._info.net['id'],
                             self._info.secgroups)
        return nodes

    def create_nodes_tasks(self,
                           host,
                           token,
                           ca_info,
                           role='node',
                           flavor=None,
                           zone=None,
                           amount=1):
        """
        Create tasks for adding nodes when running ``koris add --args ...``

        Args:
            ca_cert (CertBundle.cert)
            token (str)
            discovery_hash (str)
            host (str) - the address of the master or loadbalancer
            flavor (str or None)
            zone (str)

        """

        ca_cert = ca_info['ca_cert']
        discovery_hash = ca_info['discovery_hash']
        url = urllib.parse.urlparse(host)
        host_addr = url.netloc.split(":")[0]
        if ":" in url.netloc:
            host_port = url.netloc.split(":")[-1]
        else:
            host_port = 6443

        if flavor:
            flavor = self._info.compute_client.flavors.find(name=flavor)
        else:
            flavor = self._info.node_flavor

        nodes = self.create_new_nodes(role=role,
                                      zone=zone,
                                      amount=amount,
                                      flavor=flavor)
        nodes = self._create_nodes_tasks(ca_cert,
                                         host_addr, host_port, token,
                                         discovery_hash, nodes)
        return nodes

    @staticmethod
    def launch_new_nodes(node_tasks):
        """
        Launch all nodes when running ``koris add ...``
        """
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.gather(*node_tasks))
        loop.close()

    def get_nodes(self):
        """
        get information on the nodes from openstack.

        Return:
            list [openstack.Instance, openstack.Instance, ...]
        """

        return list(self._info.distribute_nodes())

    def create_initial_nodes(self,
                             cloud_config,
                             ca_bundle,
                             lb_ip,
                             lb_port,
                             bootstrap_token,
                             discovery_hash,
                             ):
        """
        Create all initial nodes when running ``koris apply <config>``
        """
        self.cloud_config = cloud_config

        nodes = self.get_nodes()
        nodes = self._create_nodes_tasks(ca_bundle.cert,
                                         lb_ip, lb_port, bootstrap_token,
                                         discovery_hash, nodes)
        return nodes

    def _create_nodes_tasks(self,
                            ca_cert,
                            lb_ip,
                            lb_port,
                            bootstrap_token,
                            discovery_hash,
                            nodes):
        """
        Create future tasks for creating the cluster worker nodes
        """
        loop = asyncio.get_event_loop()
        tasks = []

        for node in nodes:
            if node.exists:
                raise InstanceExists("Node {} already exists! Skipping "
                                     "creation of the cluster.".format(node))

            userdata = str(NodeInit(ca_cert, self.cloud_config, lb_ip, lb_port,
                                    bootstrap_token,
                                    discovery_hash))
            tasks.append(loop.create_task(
                node.create(node.flavor, self._info.secgroups,
                            self._info.keypair, userdata)
            ))

        return tasks


class ControlPlaneBuilder:  # pylint: disable=too-many-locals,too-many-arguments
    """
    Interact with openstack and create a virtual machines with a volume,
    and network interface. The machines are provisioned with cloud-init.
    This class builds the control plane machine, and although it is similar
    to NodeBuilder it uses a bit slightly different methods under the hood to
    configure the control plane services.

    Args:
        nova (nova client instance) - to create a volume and a machine
        neutron (neutron client instance) - to create a network interface
        config (dict) - the parsed configuration file
    """

    def __init__(self, config, osinfo):
        LOGGER.info("gathering control plane information from openstack ...")
        self._config = config
        self._info = osinfo

    def get_masters(self):
        """
        get information on the nodes from openstack.

        Return:
            list [openstack.Instance, openstack.Instance, ...]
        """
        return list(self._info.distribute_management())

    def create_masters_tasks(self, ssh_key, ca_bundle, cloud_config, lb_ip,
                             lb_port, bootstrap_token, lb_dns='',
                             pod_subnet="10.233.0.0/16",
                             pod_network="CALICO"):
        """
        Create future tasks for creating the cluster control plane nodesself.
        """

        masters = self.get_masters()
        if not len(masters) % 2:
            LOGGER.warnning("The number of masters should be odd!")
            return []

        loop = asyncio.get_event_loop()
        tasks = []

        for index, master in enumerate(masters):
            if master.exists:
                raise InstanceExists("Node {} already exists! Skipping "
                                     "creation of the cluster.".format(master))
            if not index:
                # create userdata for first master node if not existing
                userdata = str(FirstMasterInit(ssh_key, ca_bundle,
                                               cloud_config, masters,
                                               lb_ip, lb_port,
                                               bootstrap_token, lb_dns,
                                               pod_subnet,
                                               pod_network))
            else:
                # create userdata for following master nodes if not existing
                userdata = str(NthMasterInit(cloud_config, ssh_key))

            tasks.append(loop.create_task(
                master.create(self._info.master_flavor, self._info.secgroups,
                              self._info.keypair, userdata)
            ))

        return tasks


class ClusterBuilder:  # pylint: disable=too-few-public-methods

    """
    Plan and build a kubernetes cluster in the cloud
    """
    def __init__(self, config):
        if not (config['n-masters'] % 2 and config['n-masters'] >= 1):
            print(red("You must have an odd number (>=1) of masters!"))
            sys.exit(2)

        self.info = OSClusterInfo(NOVA, NEUTRON, CINDER, config)
        LOGGER.debug(info("Done collecting information from OpenStack"))

        self.nodes_builder = NodeBuilder(config, self.info)
        self.masters_builder = ControlPlaneBuilder(config, self.info)

    @staticmethod
    def create_bootstrap_token():
        """create a new random bootstrap token like f62bcr.fedcba9876543210,
        a valid token matches the expression [a-z0-9]{6}.[a-z0-9]{16}"""
        token = "".join([random.choice(string.ascii_lowercase + string.digits)
                         for n in range(6)])
        token += "."
        token = token + "".join([random.choice(string.ascii_lowercase + string.digits)
                                 for n in range(16)])
        return token

    @staticmethod
    def calculate_discovery_hash(ca_bundle):
        """
        calculate the discovery hash based on the ca_bundle
        """
        return get_discovery_hash(ca_bundle.cert)

    @staticmethod
    def create_ca():
        """create a self signed CA"""
        _key = create_key(size=2048)
        _ca = create_ca(_key, _key.public_key(),
                        "DE", "BY", "NUE",
                        "Kubernetes", "CDA-RT",
                        "kubernetes-ca")
        return CertBundle(_key, _ca)

    def run(self, config):  # pylint: disable=too-many-locals,too-many-statements
        """
        execute the complete cluster build
        """
        # create a security group for the cluster if not already present
        if self.info.secgroup.exists:
            LOGGER.info(info(red(
                "A Security group named %s-sec-group already exists" % config[
                    'cluster-name'])))
            LOGGER.info(
                info(red("I will add my own rules, please manually review all others")))  # noqa

        self.info.secgroup.configure()

        try:
            subnet = NEUTRON.find_resource('subnet', config['subnet'])
        except KeyError:
            subnet = NEUTRON.list_subnets()['subnets'][-1]

        cloud_config = OSCloudConfig(subnet['id'])
        LOGGER.info("Using subnet %s", subnet['name'])

        # generate CA key pair for the cluster, that is used to authenticate
        # the clients that can use kubeadm
        ca_bundle = self.create_ca()
        cert_dir = "-".join(("certs", config["cluster-name"]))
        ca_bundle.save("k8s", cert_dir)

        # generate ssh key pair for first master node. It is used to connect
        # to the other nodes so that they can join the cluster
        ssh_key = create_key()

        # create a load balancer for accessing the API server of the cluster;
        # do not add a listener, since we created no machines yet.
        LOGGER.info("Creating the load balancer...")
        lbinst = LoadBalancer(config)
        lb, floatingip = lbinst.get_or_create(NEUTRON)
        lb_port = "6443"

        lb_dns = config['loadbalancer'].get('dnsname') or floatingip
        lb_ip = floatingip if floatingip else lb['vip_address']

        # calculate information needed for joining nodes to the cluster...
        # calculate bootstrap token
        bootstrap_token = ClusterBuilder.create_bootstrap_token()

        # calculate discovery hash
        discovery_hash = self.calculate_discovery_hash(ca_bundle)

        # create the master nodes with ssh_key (private and public key)
        # first task in returned list is task for first master node
        LOGGER.info("Waiting for the master machines to be launched...")
        master_tasks = self.masters_builder.create_masters_tasks(
            ssh_key, ca_bundle, cloud_config, lb_ip, lb_port,
            bootstrap_token, lb_dns,
            config.get("pod_subnet", "10.233.0.0/16"),
            config.get("pod_network", "CALICO"))
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(asyncio.gather(*master_tasks))

        # add a listener for the first master node, since this is the node we
        # call kubeadm init on
        LOGGER.info("Configuring the LoadBalancer...")
        first_master_ip = results[0].ip_address
        configure_lb_task = loop.create_task(
            lbinst.configure(NEUTRON, [first_master_ip]))

        # create the worker nodes
        LOGGER.info("Waiting for the worker machines to be launched...")
        node_tasks = self.nodes_builder.create_initial_nodes(
            cloud_config,
            ca_bundle, lb_ip, lb_port, bootstrap_token, discovery_hash)

        # WORK: setting up LB for Dex
        LOGGER.info("Configuring the LoadBalancer for Dex ...")
        dex = Dex(lbinst, members=[first_master_ip])
        configure_dex_task = loop.create_task(dex.configure_lb(NEUTRON))
        node_tasks.append(configure_dex_task)

        node_tasks.append(configure_lb_task)
        results = loop.run_until_complete(asyncio.gather(*node_tasks))
        LOGGER.debug(info("Done creating nodes tasks"))

        # We should no be able to query the API server for available nodes
        # with a valid certificate from the generated CA. Hence, generate
        # a client certificate.
        LOGGER.info("Talking to the API server and waiting for masters to be "
                    "online.")
        client_cert = CertBundle.create_signed(
            ca_bundle, "DE", "BY", "NUE", "system:masters", "system:masters",
            "kubernetes-admin", "", "")
        client_cert.save("k8s-client", cert_dir)

        kubeconfig = write_kubeconfig(config["cluster-name"], lb_ip,
                                      lb_port, cert_dir, "k8s.pem",
                                      "k8s-client.pem", "k8s-client-key.pem")

        # Now connect to the the API server and query which masters are
        # available.
        k8s = K8S(kubeconfig)

        LOGGER.handlers[0].terminator = ""
        LOGGER.info("Kubernetes API Server is still not ready ...")
        while not k8s.is_ready:
            time.sleep(2)
            LOGGER.info(".")

        LOGGER.handlers[0].terminator = "\n"

        LOGGER.info("\nKubernetes API is ready!"
                    "\nWaiting for all masters to become Ready")
        k8s.add_all_masters_to_loadbalancer(len(master_tasks), lbinst, NEUTRON)

        LOGGER.info("Configured load balancer to use all API servers")

        # At this point, we're ready with our cluster
        LOGGER.info("Kubernetes cluster is ready to use !!!")
        loop.close()
