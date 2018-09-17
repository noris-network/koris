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
from kolt.util.hue import red, info, lightcyan as cyan

from kolt.util.util import (EtcdHost,
                            create_inventory,
                            get_logger,
                            get_token_csv)
from .openstack import OSClusterInfo
from .openstack import (get_clients,
                        OSCloudConfig,
                        create_instance_with_volume,
                        create_loadbalancer)

logger = get_logger(__name__)

nova, neutron, cinder = get_clients()


class NodeBuilder:

    def __init__(self, nova, neutron, config):
        logger.info(info(cyan(
            "gathering node information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, config)

    def create_userdata(self, cluster_info=None, cloud_provider=None,
                        cert_bundle=None, encryption_key=None, **kwargs):
        kubelet_token = kwargs.get('kubelet_token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        service_account_bundle = kwargs.get('service_account_bundle')
        lb_ip = kwargs.get("lb_ip")
        userdata = str(NodeInit(kubelet_token, ca_cert,
                                cert_bundle, service_account_bundle,
                                cluster_info, calico_token, lb_ip))
        return userdata

    def get_nodes_info(self, nova, neutron, config):
        """
        Find if hosts already exists, if they don't exist already create
        a future task for creating a NIC for attaching it to a host.
        calculate node names and zone, build nics
        """

        return self._info.nodes_status

    def create_hosts_tasks(self, nics, hosts, certs,
                           kubelet_token,
                           calico_token,
                           etcd_host_list,
                           lb_ip,
                           no_cloud_init=False
                           ):
        node_args = {'kubelet_token': kubelet_token,
                     'cluster_info': etcd_host_list,
                     'calico_token': calico_token,
                     }

        node_args.update({'ca_cert': certs['ca'],
                          'service_account_bundle': certs[
                              'service-account'],  # noqa
                          'cert_bundle': certs['k8s'],
                          'lb_ip': lb_ip})

        user_data = self.create_userdata(**node_args)
        task_args_node = self._info.node_args_builder(user_data, hosts)

        hosts = self._info.distribute_nodes()

        self._info.assign_nics_to_nodes(hosts, nics)
        volume_klass = self._info.storage_class
        loop = asyncio.get_event_loop()

        tasks = [loop.create_task(create_instance_with_volume(
            host.name, host.zone,
            nics=host.nic, volume_klass=volume_klass, nova=nova, cinder=cinder,
            neutron=neutron,
            *task_args_node))
            for host in hosts]

        return tasks


class ControlPlaneBuilder:

    def __init__(self, nova, neutron, config):

        logger.info(info(cyan(
            "gathering control plane information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, config)

    def create_userdata(self, cluster_info=None, cloud_provider=None,
                        cert_bundle=None, encryption_key=None, **kwargs):
        userdata = str(MasterInit(cluster_info, cert_bundle,
                                  encryption_key,
                                  cloud_provider, **kwargs))
        return userdata

    def get_hosts_info(self):
        return self._info.management_status

    def create_hosts_tasks(self, nics, hosts, certs,
                           kubelet_token,
                           calico_token,
                           admin_token,
                           etcd_host_list,
                           no_cloud_init=False):

        # generate a random string
        # this should be the equal of
        # ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)

        encryption_key = base64.b64encode(
            uuid.uuid4().hex[:32].encode()).decode()

        cloud_provider_info = OSCloudConfig()

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

        tasks_args_masters = self._info.master_args_builder(user_data, hosts)

        masters_zones = self._info.distribute_management()
        self._info.assign_nics_to_management(masters_zones, nics)

        volume_klass = self._info.storage_class
        loop = asyncio.get_event_loop()

        tasks = [loop.create_task(create_instance_with_volume(
                 masters_zones[i].name, masters_zones[i].zone,
                 nics=masters_zones[i].nic,
                 volume_klass=volume_klass,
                 nova=nova, cinder=cinder, neutron=neutron,
                 *tasks_args_masters)) for i in range(0, self._info.n_masters)]

        return tasks


class ClusterBuilder:

    def run(self, config, no_cloud_init=False):

        if not (config['n-etcds'] % 2 and config['n-etcds'] > 1):
            print(red("You must have an odd number (>1) of etcd machines!"))
            sys.exit(2)

        nb = NodeBuilder(nova, neutron, config)
        cpb = ControlPlaneBuilder(nova, neutron, config)
        logger.debug(info("Done collecting infromation from OpenStack"))
        worker_nodes = nb.get_nodes_info(nova, neutron, config)

        cp_hosts = cpb.get_hosts_info()
        etcd_host_list = []

        for server in cp_hosts:
            etcd_host_list.append(EtcdHost(server.name, server.ip_address))

        node_ips = [node.ip_address for node in worker_nodes]

        ips = [str(host.ip_address) for host in etcd_host_list
               ] + list(node_ips) + ['127.0.0.1', "10.32.0.1"]

        cluster_host_names = [host.name for host in etcd_host_list] + [
            host.name for host in worker_nodes] + [
            "kubernetes.default", "kubernetes.default.svc.cluster.local"]
        nics = [host.interface_list()[0] for host in worker_nodes]
        cp_nics = [host.interface_list()[0] for host in cp_hosts]
        nics = [nic for nic in nics if
                not isinstance(nic, novaclient.v2.servers.NetworkInterface)]
        cp_nics = [nic for nic in cp_nics if
                   not isinstance(nic, novaclient.v2.servers.NetworkInterface)]

        # stupid check which needs to be improved!
        if not (nics + cp_nics):
            logger.info(info(red("Skipping certificate creations")))
            tasks = []
            logger.debug(info("Not creating any tasks"))
        else:
            subnet = config.get('subnent')
            kwargs = {'subnent': subnet} if subnet else {}
            lb = create_loadbalancer(
                neutron, config['private_net'],
                config['cluster-name'],
                [str(host.ip_address) for host in etcd_host_list],  # noqa
                **kwargs)
            ips.append(lb['vip_address'])
            certs = create_certs(config, cluster_host_names, ips)
            logger.debug(info("Done creating nodes tasks"))

            if no_cloud_init:
                certs = None
                calico_token = None
                kubelet_token = None
                admin_token = None
            else:
                calico_token = uuid.uuid4().hex[:32]
                kubelet_token = uuid.uuid4().hex[:32]
                admin_token = uuid.uuid4().hex[:32]

            hosts = {}

            tasks = nb.create_hosts_tasks(nics, hosts, certs, kubelet_token,
                                          calico_token, etcd_host_list,
                                          no_cloud_init=no_cloud_init,
                                          lb_ip=lb['vip_address'])

            cp_tasks = cpb.create_hosts_tasks(cp_nics, hosts, certs,
                                              kubelet_token, calico_token,
                                              admin_token,
                                              etcd_host_list,
                                              no_cloud_init=no_cloud_init)

            logger.debug(info("Done creating control plane tasks"))

            tasks = cp_tasks + tasks

        if tasks:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(asyncio.wait(tasks))
            loop.close()
            kubeconfig = write_kubeconfig(config, lb['vip_address'],
                                          admin_token,
                                          True)

            logger.info("Waiting for K8S API server to launch")

            manifest_path = os.path.join("kolt", "deploy", "manifests")
            k8s = K8S(kubeconfig, manifest_path)

            while not k8s.is_ready:
                logger.debug("Kubernetes API Server is still not ready ...")
                time.sleep(2)

            logger.debug("Kubernetes API Server is ready !!!")
            ####
            #
            # TODO: URGENTLY REPLACE THIS HACK BELOW WITH AN OPENSTACK LB
            #
            ####

            lb_url = "https://%s:%d" % (
                etcd_host_list[0].ip_address, etcd_host_list[0].port - 1)
            k8s.apply_calico(b64_key(certs["k8s"].key),
                             b64_cert(certs["k8s"].cert),
                             b64_cert(certs["ca"].cert),
                             lb_url)
            k8s.apply_kube_dns()

            # more roles come here later ...

        if no_cloud_init:
            return create_inventory(hosts, config)
