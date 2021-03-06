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

import openstack
from cryptography.hazmat.primitives import serialization

from koris import KUBERNETES_BASE_VERSION
from koris.cli import write_kubeconfig
from koris.deploy.k8s import K8S, add_ingress_listeners
from koris.provision.cloud_init import FirstMasterInit, NthMasterInit, NodeInit
from koris.ssl import create_key, create_ca, CertBundle
from koris.ssl import discovery_hash as get_discovery_hash
from koris.deploy.dex import (create_dex, create_oauth2, DexSSL,
                              create_dex_conf, ValidationError)
from koris.util.logger import Logger
from koris.ssl import b64_cert, b64_key
from .openstack import (Instance, OSCloudConfig, LoadBalancer, InstanceExists)


LOGGER = Logger(__name__)


def get_server_range(servers, cluster_name, role, amount):
    """
    Given a list of servers find the last server name and add N more
    """
    servers = [s for s in servers if
               s.name.startswith(cluster_name)]
    servers = [s for s in servers if role in s.name]

    lastname = sorted(servers, key=lambda x: x.name)[-1].name
    idx = int(lastname.split('-')[-1])
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
        LOGGER.debug("Gathering node information from OpenStack ...")
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

        self._info.setup_networking()
        nodes = [Instance(self._info.storage_client,
                          self._info.compute_client,
                          '%s-%s-%d' % (self.config['cluster-name'], role, n),
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

    # pylint: disable=too-many-arguments,too-many-locals
    def create_nodes_tasks(self,
                           host,
                           token,
                           ca_info,
                           role='node',
                           flavor=None,
                           zone=None,
                           amount=1,
                           k8s_version=KUBERNETES_BASE_VERSION):
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
                                         discovery_hash, nodes,
                                         k8s_version=k8s_version)
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
                             k8s_version=KUBERNETES_BASE_VERSION,
                             pod_network="CALICO"):
        """
        Create all initial nodes when running ``koris apply <config>``
        """
        self.cloud_config = cloud_config

        nodes = self.get_nodes()
        nodes = self._create_nodes_tasks(ca_bundle.cert,
                                         lb_ip, lb_port, bootstrap_token,
                                         discovery_hash, nodes,
                                         k8s_version=k8s_version,
                                         pod_network=pod_network)
        return nodes

    def _create_nodes_tasks(self,
                            ca_cert,
                            lb_ip,
                            lb_port,
                            bootstrap_token,
                            discovery_hash,
                            nodes,
                            k8s_version=KUBERNETES_BASE_VERSION,
                            pod_network="CALICO"):
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
                                    discovery_hash,
                                    k8s_version=k8s_version,
                                    pod_network=pod_network))
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
        config (dict) - the parsed configuration file
        osinfo (OSClusterInfo) - information about the currect cluster
        cloud_config (OSCloudConfig) - the cloud config generator
    """

    def __init__(self, config, osinfo, cloud_config=None):
        LOGGER.debug("Gathering control plane information from OpenStack ...")
        self._config = config
        self._info = osinfo
        self.cloud_config = cloud_config

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
                             pod_network="CALICO", dex=None,
                             k8s_version=KUBERNETES_BASE_VERSION):
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
                koris_env = {
                    "master_ips": [master.ip_address for master in masters],
                    "master_names": [master.name for master in masters],
                    "lb_dns": lb_dns,
                    "lb_ip": lb_ip,
                    "lb_port": lb_port,
                    "bootstrap_token": bootstrap_token,
                    "pod_subnet": pod_subnet,
                    "pod_network": pod_network,
                    "k8s_version": k8s_version
                }

                userdata = str(FirstMasterInit(ssh_key, ca_bundle,
                                               cloud_config,
                                               dex=dex,
                                               koris_env=koris_env))
            else:
                # create userdata for following master nodes if not existing
                koris_env = {"k8s_version": k8s_version,
                             "auto_join": 0}
                userdata = str(NthMasterInit(cloud_config, ssh_key, dex=dex,
                                             koris_env=koris_env))

            tasks.append(loop.create_task(
                master.create(self._info.master_flavor, self._info.secgroups,
                              self._info.keypair, userdata)
            ))

        return tasks

    def create_new_master(self,
                          zone=None,
                          flavor=None,
                          ):
        """
        Creates a new instance in OpenStack and labels it as a K8s master

        Args:
            zone (str): The noris.cloud availability zone to create the master in.
            flavor (str): The noris.cloude instance flavor of the master.

        Returns:
            An instance of `:class:koris.cloud.openstack.Instance` which
            represents the added master.
        """
        role = 'master'
        master_number = next(iter(
            get_server_range(self._info.compute_client.servers.list(),
                             self._config['cluster-name'],
                             role,
                             1)))

        master = Instance(self._info.storage_client,
                          self._info.compute_client,
                          '%s-%s-%s' % (self._config['cluster-name'],
                                        role, master_number
                                        ),
                          self._info.net,
                          zone,
                          role,
                          {'image': self._info.image,
                           'class': self._info.storage_class},
                          flavor
                          )
        master.attach_port(self._info.netclient, self._info.net['id'],
                           self._info.secgroups)
        return master

    def add_master(
            self,
            zone,
            flavor,
            k8s_version=KUBERNETES_BASE_VERSION,
            k8s_conf=None,
            **kwargs):
        """Adds a new instance in OpenStack which will be provisioned as master.

        - Create a new machine
        - Grab the public key from OpenStack so the master-add-pod can SSH to it.

        Args:
          zone (str): The noris.cloud availability zone to create the master in.
          flavor (str): The noris.cloud instance flavor of the master.

        Returns:
          The results of the asyncio task.
        """

        cloud_config = self.cloud_config
        master = self.create_new_master(zone, flavor)

        loop = asyncio.get_event_loop()

        key = self._info.conn.compute.find_keypair(self._info.name)

        koris_env = {"k8s_version": k8s_version}
        koris_env.update(kwargs.get('koris_env', {}))

        init = NthMasterInit(
            cloud_config,
            key.public_key,
            koris_env=koris_env,
            k8s_conf=k8s_conf,
        )

        userdata = str(init)
        task = loop.create_task(master.create(
            self._info.master_flavor, self._info.secgroups, self._info.keypair,
            userdata))

        loop.run_until_complete(*[task])

        return task.result()


class ClusterBuilder:  # pylint: disable=too-few-public-methods
    """
    Plan and build a kubernetes cluster in the cloud
    """
    def __init__(self, config, oscinfo, nova, neutron, cinder, conn):
        if not (config['n-masters'] % 2 and config['n-masters'] >= 1):
            LOGGER.error("You must have an odd number (>=1) of masters!")
            sys.exit(2)

        self.nova, self.neutron, self.cinder = nova, neutron, cinder
        self.conn = conn
        self.info = oscinfo

        self.nodes_builder = NodeBuilder(config, self.info)
        self.masters_builder = ControlPlaneBuilder(config, self.info)

        self.deploy_dex = False
        self.dex_conf = None

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

    def create_ssh_keypair(self):
        """Generates a keypair for the first master node.

        The master node needs a keypair which is uploaded to OpenStack. This
        keypair is then used for adding master nodes to the cluster.

        This key pair is also added as a secret to the master-adder-pod.

        Returns:
            An OpenStack keypair.
        """

        ssh_key = create_key()
        pub_key_ascii = ssh_key.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH).decode()
        try:
            self.info.conn.compute.create_keypair(name=self.info.name,
                                                  public_key=pub_key_ascii)
        except openstack.exceptions.ConflictException:
            self.info.conn.compute.delete_keypair(self.info.name)
            self.info.conn.compute.create_keypair(name=self.info.name,
                                                  public_key=pub_key_ascii)

        return ssh_key

    def create_network(self):
        """Sets up networking for the cluster."""

        self.info.setup_networking()
        self.info.secgroup.configure()

        subnet = self.info.subnet
        cloud_config = OSCloudConfig(subnet['id'])

        return cloud_config

    def run(self, config):  # pylint: disable=too-many-locals,too-many-statements
        """
        execute the complete cluster build
        """

        # Extract Kubernetes version
        if 'version' in config and 'k8s' in config['version']:
            k8s_version = config['version']['k8s']
        else:
            k8s_version = KUBERNETES_BASE_VERSION

        LOGGER.info("Building Kubernetes %s cluster '%s'",
                    k8s_version, config['cluster-name'])

        LOGGER.info("Setting up networking ...")
        cloud_config = self.create_network()
        # generate CA key pair for the cluster, that is used to authenticate
        # the clients that can use kubeadm

        LOGGER.info("Creating Kubernetes CA ...")
        ca_bundle = self.create_ca()
        ssh_key = self.create_ssh_keypair()
        cert_dir = "-".join(("certs", config["cluster-name"]))

        # Check if dex has to be deployed
        if 'addons' in config and 'dex' in config['addons']:
            self.deploy_dex = True
            LOGGER.info("Addons: Dex will be configured")

        # generate ssh key pair for first master node. It is used to connect
        # to the other nodes so that they can join the cluster
        ssh_key = self.create_ssh_keypair()

        # create a load balancer for accessing the API server of the cluster;
        # do not add a listener, since we created no machines yet.
        LOGGER.info("Creating the LoadBalancer ...")
        lbinst = LoadBalancer(config, self.conn, self.neutron)
        lb, floatingip = lbinst.get_or_create()
        lb_port = "6443"

        lb_dns = config.get('loadbalancer', {}).get('dnsname') or floatingip
        lb_ip = floatingip if floatingip else lb['vip_address']

        # calculate information needed for joining nodes to the cluster...
        # calculate bootstrap token
        bootstrap_token = ClusterBuilder.create_bootstrap_token()

        # calculate discovery hash
        discovery_hash = self.calculate_discovery_hash(ca_bundle)

        if self.deploy_dex:
            LOGGER.info("Setting up Dex SSL infrastructure ...")
            # Dex Issuer will be set to the Floating IP, or LoadBalancer DNS Name
            if lb_dns == lb_ip or lb_dns is None:
                issuer = lb_ip
            else:
                issuer = lb_dns
            LOGGER.info("Dex CA Issuer set to %s", issuer)
            dex_ssl = DexSSL(cert_dir, issuer)
            dex_ssl.save_certs()

            try:
                self.dex_conf = create_dex_conf(config['addons']['dex'], dex_ssl)
            except (ValidationError, TypeError, KeyError) as exc:
                LOGGER.error(f"Unable to parse dex config: {exc}")
                LOGGER.error("Skipping Dex deployment")
                self.deploy_dex = False
                self.dex_conf = None

        # create the master nodes with ssh_key (private and public key)
        # first task in returned list is task for first master node
        LOGGER.info("Waiting for master instances to be launched...")
        master_tasks = self.masters_builder.create_masters_tasks(
            ssh_key, ca_bundle, cloud_config, lb_ip, lb_port,
            bootstrap_token, lb_dns,
            config.get("pod_subnet", "10.233.0.0/16"),
            config.get("pod_network", "CALICO"),
            dex=self.dex_conf,
            k8s_version=k8s_version)
        loop = asyncio.get_event_loop()
        master_results = loop.run_until_complete(asyncio.gather(*master_tasks))

        master_ips = [x.ip_address for x in master_results if
                      isinstance(x, Instance)]

        # add a listener for the first master node, since this is the node we
        # call kubeadm init on
        LOGGER.info("Configuring the LoadBalancer ...")
        first_master_ip = master_results[0].ip_address
        configure_lb_task = loop.create_task(
            lbinst.configure([first_master_ip]))

        # create the worker nodes
        LOGGER.info("Waiting for worker instances to be launched and the "
                    "LoadBalancer to be configured...")
        node_tasks = self.nodes_builder.create_initial_nodes(
            cloud_config, ca_bundle, lb_ip, lb_port, bootstrap_token,
            discovery_hash, k8s_version=k8s_version,
            pod_network=config['pod_network']
        )

        node_tasks.append(configure_lb_task)
        node_results = loop.run_until_complete(asyncio.gather(*node_tasks))
        LOGGER.debug("Finished node tasks")

        node_ips = [x.ip_address for x in node_results if isinstance(x, Instance)]

        if self.deploy_dex:
            LOGGER.info("Configuring the LoadBalancer for Dex ...")
            dex_listener = self.dex_conf['ports']['listener']
            dex_service = self.dex_conf['ports']['service']
            dex_members = master_ips
            dex_task = loop.create_task(create_dex(lbinst,
                                                   listener_port=dex_listener,
                                                   pool_port=dex_service,
                                                   members=dex_members))

            client_listener = self.dex_conf['client']['ports']['listener']
            client_service = self.dex_conf['client']['ports']['service']
            client_members = node_ips
            oauth_task = loop.create_task(create_oauth2(lbinst,
                                                        listener_port=client_listener,
                                                        pool_port=client_service,
                                                        members=client_members))
            tasks = [dex_task, oauth_task]
            loop.run_until_complete(asyncio.gather(*tasks))
            LOGGER.info("Finished configuring LoadBalancer for Dex")

        # We should no be able to query the API server for available nodes
        # with a valid certificate from the generated CA. Hence, generate
        # a client certificate.
        LOGGER.info("Talking to the API server and waiting for masters to be "
                    "online.")
        client_cert = CertBundle.create_signed(
            ca_bundle, "DE", "BY", "NUE", "system:masters", "system:masters",
            "kubernetes-admin", "", "")

        # send certificates and keys to kube config
        kubeconfig = write_kubeconfig(config["cluster-name"], lb_ip,
                                      lb_port, b64_cert(ca_bundle.cert),
                                      b64_cert(client_cert.cert),
                                      b64_key(client_cert.key))

        # Now connect to the the API server and query which masters are
        # available.
        k8s = K8S(kubeconfig)

        LOGGER.logger.handlers[0].terminator = ""
        LOGGER.info("Waiting for Kubernetes API Server to become available ...")
        while not k8s.is_ready:
            time.sleep(2)
            LOGGER.info(".", color=False)

        LOGGER.logger.handlers[0].terminator = "\n"
        LOGGER.info("", color=None)
        LOGGER.success("Kubernetes API is ready!")
        LOGGER.info("Waiting for all masters to become Ready ...")
        lb_masters = [{"name": x.name,
                       "address": x.ip_address,
                       "protocol_port": 6443,
                       "monitor_port": 6443} for x in master_results if
                      isinstance(x, Instance)]
        lb_nodes = [{"name": x.name,
                     "address": x.ip_address,
                     } for x in node_results if isinstance(x, Instance)]
        if not lbinst.bulk_update_members(lb_masters):
            k8s.add_all_masters_to_loadbalancer(config['cluster-name'],
                                                len(master_tasks), lbinst)
        k8s.apply_addons(config)
        add_ingress_listeners(k8s.nginx_ingress_ports, lbinst,
                              lb_masters + lb_nodes)
        LOGGER.success("Configured LoadBalancer to use all API servers")
        LOGGER.success("Kubernetes cluster is ready to use !")
        loop.close()
