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

from kolt.deploy.k8s import K8S

from kolt.cli import write_kubeconfig
from kolt.provision.cloud_init import MasterInit, NodeInit
from kolt.ssl import create_certs, b64_key, b64_cert, create_key, create_ca, CertBundle
from kolt.util.hue import (  # pylint: disable=no-name-in-module
    red, info, lightcyan as cyan)

from kolt.util.util import (get_logger,
                            get_token_csv)
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

    def create_userdata(self, etcd_cluster_info,
                        cert_bundle, **kwargs):
        """
        create the userdata which is given to cloud init

        Args:
            etcd_cluster_info - a list of EtcServer instances.
            This is need since calico communicates with etcd.
        """
        cloud_provider_info = OSCloudConfig(self._info.subnet_id)

        kubelet_token = kwargs.get('kubelet_token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        service_account_bundle = kwargs.get('service_account_bundle')
        lb_ip = kwargs.get("lb_ip")
        userdata = str(NodeInit(kubelet_token, ca_cert,
                                cert_bundle, service_account_bundle,
                                etcd_cluster_info, calico_token, lb_ip,
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
                     'etcd_cluster_info': etcd_host_list,
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
            node.create(self._info.node_flavor,
                        self._info.secgroups,
                        self._info.keypair,
                        user_data
                        )) for node in nodes if not node._exists]

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

        LOGGER.info(info(cyan(
            "gathering control plane information from openstack ...")))
        self._config = config
        self._info = osinfo

    def create_userdata(self,
                        etcds,
                        admin_token,
                        calico_token,
                        kubelet_token,
                        certs):
        """
        create the userdata which is given to cloud init

        Args:
            etcds - a list of Instance instances
        """
        # generate a random string
        # this should be the equal of
        # ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)

        encryption_key = base64.b64encode(
            uuid.uuid4().hex[:32].encode()).decode()
        cloud_provider = OSCloudConfig(self._info.subnet_id)

        token_csv_data = get_token_csv(admin_token,
                                       calico_token,
                                       kubelet_token)

        for host in etcds:
            userdata = str(MasterInit(host.name, etcds, certs,
                                      encryption_key,
                                      cloud_provider,
                                      token_csv_data=token_csv_data))
            yield userdata

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
                             ):
        """
        Create future tasks for creating the cluster control plane nodes
        """

        masters = self.get_masters()

        user_data = self.create_userdata(
            masters,
            admin_token,
            calico_token,
            kubelet_token,
            certs)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(
            master.create(self._info.master_flavor,
                          self._info.secgroups,
                          self._info.keypair,
                          data
                          )) for master, data in zip(masters, user_data) if
                 not master._exists]

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
        LOGGER.debug(info("Done collecting infromation from OpenStack"))

        self.nodes_builder = NodeBuilder(config, self.info)
        self.masters_builder = ControlPlaneBuilder(config, self.info)

    @staticmethod
    def _create_tokes():
        for _ in range(3):
            yield uuid.uuid4().hex[:32]

    @staticmethod
    def _cluster_ips(cp_hosts, worker_hosts):
        cluster_ips = []
        cluster_ips += [node.ip_address for node in worker_hosts]
        cluster_ips += [host.ip_address for host in cp_hosts]
        cluster_ips += ['127.0.0.1', "10.32.0.1"]
        return cluster_ips

    @staticmethod
    def _hostnames(cp_hosts, worker_hosts):
        all_hosts = []
        all_hosts += [host.name for host in cp_hosts]
        all_hosts += [host.name for host in worker_hosts]
        all_hosts += ["kubernetes.default",
                      "kubernetes.default.svc.cluster.local",
                      "kubernetes"]
        return all_hosts

    @staticmethod
    def create_ca():
        """create a self signed CA"""
        _key = create_key(size=2048)
        _ca = create_ca(_key, _key.public_key(),
                        "DE", "BY", "NUE",
                        "Kubernetes", "CDA-PI",
                        "kubernetes")
        return CertBundle(_key, _ca)

    def create_etcd_certs(self, names, ips):
        """
        create a certificate and key pair for each etcd host
        """
        ca_bundle = self.create_ca()

        api_etcd_client = CertBundle.create_signed(ca_bundle=ca_bundle,
                                                   country="",  # country
                                                   state="",  # state
                                                   locality="",  # locality
                                                   orga="system:masters",  # orga
                                                   unit="",  # unit
                                                   name="kube-apiserver-etcd-client",
                                                   hosts=[],
                                                   ips=[])

        for host, ip in zip(names, ips):
            peer = CertBundle.create_signed(ca_bundle,
                                            "",  # country
                                            "",  # state
                                            "",  # locality
                                            "",  # orga
                                            "",  # unit
                                            "kubernetes",  # name
                                            [host, 'localhost', host],
                                            [ip, '127.0.0.1', ip]
                                            )

            server = CertBundle.create_signed(ca_bundle,
                                              "",  # country
                                              "",  # state
                                              "",  # locality
                                              "",  # orga
                                              "",  # unit
                                              host,  # name CN
                                              [host, 'localhost', host],
                                              [ip, '127.0.0.1', ip]
                                              )
            yield {'%s-server' % host: server, '%s-peer' % host: peer}

        yield {'apiserver-etcd-client': api_etcd_client}
        yield {'etcd_ca': ca_bundle}

    def run(self, config):  # pylint: disable=too-many-locals
        """
        execute the complete cluster build
        """
        worker_nodes = self.nodes_builder.get_nodes()
        cp_hosts = self.masters_builder.get_masters()

        cluster_host_names = self._hostnames(cp_hosts, worker_nodes)
        cluster_ips = self._cluster_ips(cp_hosts, worker_nodes)
        loop = asyncio.get_event_loop()
        cluster_info = OSClusterInfo(NOVA, NEUTRON, CINDER, config)

        if cluster_info.secgroup._exists:
            LOGGER.info(info(red(
                "A Security group named %s-sec-group already exists" % config[
                    'cluster-name'])))
            LOGGER.info(
                info(red("I will add my own rules, please manually review all others")))  # noqa

        cluster_info.secgroup.configure()

        lbinst = LoadBalancer(config)

        lb, floatingip = lbinst.get_or_create(NEUTRON)

        configure_lb_task = loop.create_task(
            lbinst.configure(NEUTRON, [host.ip_address for host in cp_hosts]))

        if floatingip:
            lb_ip = floatingip
        else:
            lb_ip = lb['vip_address']

        cluster_ips.append(lb_ip)
        certs = create_certs(config, cluster_host_names, cluster_ips)
        etcd_certs = list(self.create_etcd_certs([host.name for host in cp_hosts],
                                                 [host.ip_address for host in
                                                  cp_hosts]))
        for item in etcd_certs:
            certs.update(item)

        LOGGER.debug(info("Done creating nodes tasks"))

        calico_t, kubelet_t, admin_t = list(self._create_tokes())
        tasks = self.nodes_builder.create_nodes_tasks(certs,
                                                      kubelet_t,
                                                      calico_t,
                                                      cp_hosts,
                                                      lb_ip)

        cp_tasks = self.masters_builder.create_masters_tasks(certs,
                                                             kubelet_t,
                                                             calico_t,
                                                             admin_t)  # noqa

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
                "https://%s:%d" % (host.ip_address, 2379)
                for host in cp_hosts)
            k8s.apply_calico(b64_key(certs["k8s"].key),
                             b64_cert(certs["k8s"].cert),
                             b64_cert(certs["ca"].cert),
                             etcd_endpoints)
            k8s.apply_kube_dns()
