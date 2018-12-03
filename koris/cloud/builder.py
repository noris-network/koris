"""
Builder
=======

Build a kubernetes cluster on a cloud
"""
import asyncio
import sys

from koris.provision.cloud_init import FirstMasterInit, NthMasterInit, NodeInit
from koris.ssl import create_key, create_ca, CertBundle
from koris.util.hue import (  # pylint: disable=no-name-in-module
    red, info, lightcyan as cyan)

from koris.util.util import get_logger
from .openstack import OSClusterInfo
from .openstack import (get_clients,
                        OSCloudConfig, LoadBalancer,
                        )

LOGGER = get_logger(__name__)

NOVA, NEUTRON, CINDER = get_clients()


class NodeBuilder:
    """
    Interact with openstack and create a virtual machines with a volume,
    and network interface. The machines are provisioned with cloud-init.

    Args:
        nova (nova client instance) - to create a volume and a machine
        neutron (neutron client instance) - to create a network interface
        config (dict) - the parsed configuration file
    """
    def __init__(self, config, osinfo):
        LOGGER.info(info(cyan(
            "gathering node information from openstack ...")))
        self.config = config
        self._info = osinfo

    def create_userdata(self, nodes, etcd_cluster_info,
                        cert_bundle, **kwargs):
        """
        create the userdata which is given to cloud init

        Args:
            nodes - a list of koris.cloud.openstack.Instance
            etcd_cluster_info - a list of EtcServer instances.
            This is need since calico communicates with etcd.
        """

        # TODO: remove after debugging
        return

        cloud_provider_info = OSCloudConfig(self._info.subnet_id)

        kubelet_token = kwargs.get('kubelet_token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        service_account_bundle = kwargs.get('service_account_bundle')
        lb_ip = kwargs.get("lb_ip")

        for node in nodes:
            userdata = str(NodeInit(node, kubelet_token, ca_cert,
                                    cert_bundle, service_account_bundle,
                                    etcd_cluster_info, calico_token, lb_ip,
                                    cloud_provider=cloud_provider_info))
            yield userdata

    def get_nodes(self):
        """
        get information on the nodes from openstack.

        Return:
            list [openstack.Instance, openstack.Instance, ...]
        """

        return list(self._info.distribute_nodes())

    def create_nodes_tasks(self, certs,
                           kubelet_token,
                           calico_token,
                           etcd_host_list,
                           lb_ip,
                           ):
        """
        Create future tasks for creating the cluster worker nodes
        """
        cloud_provider_info = OSCloudConfig(self._info.subnet_id)

        node_args = {'kubelet_token': kubelet_token,
                     'etcd_cluster_info': etcd_host_list,
                     'calico_token': calico_token,
                     }

        nodes = self.get_nodes()
        node_args.update({
            'nodes': nodes,
            'ca_cert': certs['ca'],
            'service_account_bundle': certs[
                'service-account'],  # noqa
            'cert_bundle': certs['k8s'],
            'lb_ip': lb_ip,
            'cloud_provider': cloud_provider_info})

        user_data = self.create_userdata(**node_args)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(
            node.create(self._info.node_flavor,
                        self._info.secgroups,
                        self._info.keypair,
                        data
                        )) for node, data in zip(nodes, user_data)
                 if not node._exists]

        return tasks


class ControlPlaneBuilder:
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

    def create_masters_tasks(self, cloud_config, ssh_key, ca_bundle):
        """
        Create future tasks for creating the cluster control plane nodesself.
        """
        masters = self.get_masters()
        if len(masters) < 3:
            LOGGER.warn("There should be at lest three master nodes!")
            return

        loop = asyncio.get_event_loop()
        tasks = []

        for index, master in enumerate(masters):
            if master._exists:
                LOGGER.error("Node {} is already existing! Skipping "
                             "creation.".format(master))
                continue

            if not index:
                # create userdata for first master node if not existing
                userdata = str(FirstMasterInit(ssh_key, ca_bundle,
                               cloud_config))
            else:
                # create userdata for following master nodes if not existing
                userdata = str(NthMasterInit(ssh_key))

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
        if not (config['n-etcds'] % 2 and config['n-etcds'] > 1):
            print(red("You must have an odd number (>1) of etcd machines!"))
            sys.exit(2)

        self.info = OSClusterInfo(NOVA, NEUTRON, CINDER, config)
        LOGGER.debug(info("Done collecting information from OpenStack"))

        self.nodes_builder = NodeBuilder(config, self.info)
        self.masters_builder = ControlPlaneBuilder(config, self.info)

    @staticmethod
    def create_ca():
        """create a self signed CA"""
        _key = create_key(size=2048)
        _ca = create_ca(_key, _key.public_key(),
                        "DE", "BY", "NUE",
                        "Kubernetes", "CDA-RT",
                        "kubernetes-ca")
        return CertBundle(_key, _ca)

    def run(self, config):  # pylint: disable=too-many-locals
        """
        execute the complete cluster build
        """
        if not config['subnet']:
            LOGGER.error("You must specify a subnet ID.")
            return

        loop = asyncio.get_event_loop()

        # create a security group for the cluster if not already present
        if self.info.secgroup._exists:
            LOGGER.info(info(red(
                "A Security group named %s-sec-group already exists" % config[
                    'cluster-name'])))
            LOGGER.info(
                info(red("I will add my own rules, please manually review all others")))  # noqa

        self.info.secgroup.configure()

        cloud_config = OSCloudConfig(config['subnet'])

        # generate CA key pair for the cluster, that is used to authenticate
        # the clients that can use kubeadm
        ca_bundle = self.create_ca()
        cert_dir = "-".join(("certs", config["cluster-name"]))
        ca_bundle.save("k8s", cert_dir)

        # generate ssh key pair for first master node. It is used to connect
        # to the other nodes so that they can join the cluster
        ssh_key = create_key()

        # create the master nodes with ssh_key (private and public key)
        # first task in returned list is task for first master node
        master_tasks = self.masters_builder.create_masters_tasks(
            cloud_config, ssh_key, ca_bundle)

        # create the worker node with ssh_key (public key)
        # TODO: insert after debugging
        # node_tasks = self.nodes_builder.create_nodes_tasks(ssh_key)

        # TODO: remove after debugging is finished
        # TODO: why is results [None, None, None]?!!?!?!?
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(asyncio.gather(*master_tasks))

        import pdb
        pdb.set_trace()

        # create a load balancer for accessing the API server of the cluster
        lbinst = LoadBalancer(config)
        lb, floatingip = lbinst.get_or_create(NEUTRON)

        # add a listener for the first master node, since this is the node we
        # call kubeadm init on
        # first, we need to get the IP from the first master node, maybe
        # we need to wait until booted?
        # TODO: implement

        # configure_lb_task = loop.create_task(
        #    lbinst.configure(NEUTRON, [host.ip_address for host in cp_hosts]))

        # wait until the create tasks are finished
        LOGGER.info("Waiting for the machines to be launched...")
        tasks = master_tasks + node_tasks
        # tasks = master_tasks + node_tasks + configure_lb_task
        if tasks:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(asyncio.gather(*tasks))

        # We should no be able to query the API server for available nodes
        # with a valid certificate from the generated CA. Hence, generate
        # a client certificate and connect the the API server and query which
        # nodes are available. If every node is available and running, continue
        # TODO: implement

        # Finally, we want to add the other master nodes to the LoadBalancer
        # TODO: implement

        # At this point, we're ready with our cluster
        LOGGER.debug(info("Done creating nodes tasks"))
        LOGGER.info("Kubernetes API Server is ready !!!")
