"""
Builder
=======

Build a kubernetes cluster on a cloud
"""
import asyncio
import base64
import os
import uuid
import sys
import time

import novaclient.v2.servers

from kolt.deploy.k8s import K8S

from kolt.cli import write_kubeconfig
from kolt.provision.cloud_init import MasterInit, NodeInit
from kolt.ssl import create_certs, b64_key, b64_cert
from kolt.util.hue import (  # pylint: disable=no-name-in-module
    red, info, lightcyan as cyan)

from kolt.util.util import (EtcdHost,
                            get_logger,
                            get_token_csv)
from .openstack import OSClusterInfo
from .openstack import (get_clients,
                        OSCloudConfig, LoadBalancer,
                        config_sec_group,
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
    def __init__(self, nova, neutron, cinder, config):
        LOGGER.info(info(cyan(
            "gathering node information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, cinder, config)
        self.config = config

    def create_userdata(self, cluster_info=None,
                        cert_bundle=None, **kwargs):
        """
        create the userdata which is given to cloud init
        """
        cloud_provider_info = OSCloudConfig(self._info.subnet_id)

        kubelet_token = kwargs.get('kubelet_token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        service_account_bundle = kwargs.get('service_account_bundle')
        lb_ip = kwargs.get("lb_ip")
        userdata = str(NodeInit(kubelet_token, ca_cert,
                                cert_bundle, service_account_bundle,
                                cluster_info, calico_token, lb_ip,
                                cloud_provider=cloud_provider_info))
        return userdata

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
                     'cluster_info': etcd_host_list,
                     'calico_token': calico_token,
                     }

        node_args.update({'ca_cert': certs['ca'],
                          'service_account_bundle': certs[
                              'service-account'],  # noqa
                          'cert_bundle': certs['k8s'],
                          'lb_ip': lb_ip,
                          'cloud_provider': cloud_provider_info})

        user_data = self.create_userdata(**node_args)
        nodes = self.get_nodes()

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(
            node.create(self.config['node_flavor'],
                        self._info.secgroups,
                        self._info.keypair,
                        user_data
                        )) for node in nodes]

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

    def __init__(self, nova, neutron, cinder, config):

        LOGGER.info(info(cyan(
            "gathering control plane information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, cinder, config)
        self._config = config

    def create_userdata(self, cluster_info=None, cloud_provider=None,
                        cert_bundle=None, encryption_key=None, **kwargs):
        """
        create the userdata which is given to cloud init

        Args:
            cloud_provider (OSCloudConfig) - used to write cloud.conf
        """
        OSCloudConfig(self._info.subnet_id)

        userdata = str(MasterInit(cluster_info, cert_bundle,
                                  encryption_key,
                                  cloud_provider, **kwargs))
        return userdata

    def get_masters(self):
        """
        get information on the nodes from openstack.

        Return:
            list [openstack.Instance, openstack.Instance, ...]
        """

        return list(self._info.distribute_management())

    def create_masters_tasks(self, certs,
                             kubelet_token,
                             calico_token,
                             admin_token,
                             etcd_host_list,
                             ):
        """
        Create future tasks for creating the cluster control plane nodes
        """

        # generate a random string
        # this should be the equal of
        # ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)

        encryption_key = base64.b64encode(
            uuid.uuid4().hex[:32].encode()).decode()

        cloud_provider_info = OSCloudConfig(self._info.subnet_id)

        token_csv_data = get_token_csv(admin_token,
                                       calico_token,
                                       kubelet_token)

        master_args = dict(
            cloud_provider=cloud_provider_info,
            encryption_key=encryption_key,
            token_csv_data=token_csv_data,
            cluster_info=etcd_host_list,
        )

        master_args.update({'cert_bundle':
                            (certs['ca'], certs['k8s'],
                             certs['service-account'])})

        user_data = self.create_userdata(**master_args)
        masters = self.get_masters()
        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(
            master.create(self._config['master_flavor'],
                          self._info.secgroups,
                          self._info.keypair,
                          user_data
                          )) for master in masters]

        return tasks


class ClusterBuilder:  # pylint: disable=too-few-public-methods

    """
    Plan and build a kubernetes cluster in the cloud
    """
    def __init__(self, config):
        if not (config['n-etcds'] % 2 and config['n-etcds'] > 1):
            print(red("You must have an odd number (>1) of etcd machines!"))
            sys.exit(2)

        self.nodes_builder = NodeBuilder(NOVA, NEUTRON, CINDER, config)
        self.masters_builder = ControlPlaneBuilder(NOVA, NEUTRON, CINDER, config)
        LOGGER.debug(info("Done collecting infromation from OpenStack"))

    @staticmethod
    def _create_tokes():
        for _ in range(3):
            yield uuid.uuid4().hex[:32]

    def run(self, config):  # pylint: disable=too-many-locals
        """
        execute the complete cluster build
        """
        worker_nodes = self.nodes_builder.get_nodes()
        cp_hosts = self.masters_builder.get_masters()

        etcd_hosts = [EtcdHost(server.name, server.ip_address) for server in cp_hosts]  # noqa

        node_ips = [node.ip_address for node in worker_nodes]

        ips = [str(host.ip_address) for host in etcd_hosts
               ] + list(node_ips) + ['127.0.0.1', "10.32.0.1"]

        cluster_host_names = [host.name for host in etcd_hosts] + [
            host.name for host in worker_nodes] + [
                "kubernetes.default", "kubernetes.default.svc.cluster.local",
                "kubernetes"]
        nics = [host.interface_list()[0] for host in worker_nodes]
        cp_nics = [host.interface_list()[0] for host in cp_hosts]
        nics = [nic for nic in nics if
                not isinstance(nic, novaclient.v2.servers.NetworkInterface)]
        cp_nics = [nic for nic in cp_nics if
                   not isinstance(nic, novaclient.v2.servers.NetworkInterface)]

        # stupid check which needs to be improved!
        if not nics + cp_nics:
            LOGGER.info(info(red("Skipping certificate creations")))
            tasks = []
        else:
            loop = asyncio.get_event_loop()
            cluster_info = OSClusterInfo(NOVA, NEUTRON, CINDER, config)

            config_sec_group(NEUTRON, cluster_info.secgroup['id'])

            master_ips = [str(host.ip_address) for host in etcd_hosts]

            lbinst = LoadBalancer(config)

            lb, floatingip = lbinst.create(NEUTRON)

            configure_lb_task = loop.create_task(lbinst.configure(NEUTRON,
                                                                  master_ips))

            lb = lb['loadbalancer']

            if floatingip:
                lb_ip = floatingip
            else:
                lb_ip = lb['vip_address']

            ips.append(lb_ip)
            certs = create_certs(config, cluster_host_names, ips)
            LOGGER.debug(info("Done creating nodes tasks"))

            calico_t, kubelet_t, admin_t = list(self._create_tokes())
            tasks = self.nodes_builder.create_nodes_tasks(certs,
                                                          kubelet_t,
                                                          calico_t,
                                                          etcd_hosts,
                                                          lb_ip)

            cp_tasks = self.masters_builder.create_masters_tasks(certs,
                                                                 kubelet_t,
                                                                 calico_t,
                                                                 admin_t,
                                                                 etcd_hosts)  # noqa

            LOGGER.debug(info("Done creating control plane tasks"))

            tasks = cp_tasks + tasks

        if tasks:
            loop = asyncio.get_event_loop()
            tasks.append(configure_lb_task)
            loop.run_until_complete(asyncio.gather(*tasks))
            kubeconfig = write_kubeconfig(config, lb_ip,
                                          admin_t,
                                          True)

            LOGGER.info("Waiting for K8S API server to launch")

            manifest_path = os.path.join("kolt", "deploy", "manifests")
            k8s = K8S(kubeconfig, manifest_path)

            while not k8s.is_ready:
                LOGGER.info("Kubernetes API Server is still not ready ...")
                time.sleep(2)

            LOGGER.info("Kubernetes API Server is ready !!!")

            etcd_endpoints = ",".join(
                "https://%s:%d" % (
                    etcd_host.ip_address, etcd_host.port - 1)
                for etcd_host in etcd_hosts)
            k8s.apply_calico(b64_key(certs["k8s"].key),
                             b64_cert(certs["k8s"].cert),
                             b64_cert(certs["ca"].cert),
                             etcd_endpoints)
            k8s.apply_kube_dns()
