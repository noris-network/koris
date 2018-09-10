# https://support.ultimum.io/support/solutions/articles/1000125460-python-novaclient-neutronclient-glanceclient-swiftclient-heatclient
# http://docs.openstack.org/developer/python-novaclient/ref/v2/servers.html
import asyncio
import base64
import copy
import os
import uuid
import textwrap
import sys
import time

import yaml

import novaclient.v2.servers

from mach import mach1
from novaclient import client as nvclient
from novaclient.exceptions import (NotFound as NovaNotFound,
                                   ClientException as NovaClientException)
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient

from keystoneauth1 import identity
from keystoneauth1 import session

from .cli import (delete_cluster, create_certs,
                  write_kubeconfig)  # noqa
from .cloud import MasterInit, NodeInit
from .hue import red, info, que, lightcyan as cyan, yellow
from .k8s import K8S
from .ssl import CertBundle, b64_key, b64_cert
from .util import (EtcdHost,
                   OSCloudConfig, OSClusterInfo,
                   create_inventory,
                   get_logger,
                   get_server_info_from_openstack,
                   get_token_csv,
                   )

logger = get_logger(__name__)


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


def distribute_hosts(hosts_zones):
    """
    Given  [(['host1', 'host2', 'host3'], 'A'), (['host4', 'host5'], 'B')]
    return:
    [(host1, zone),
     (host2, zone),
     (host3, zone),
     (host4, zone),
     (host5, zone)]
    """
    for item in hosts_zones:
        hosts, zone = item[0], item[1]
        for host in hosts:
            yield [host, zone, None]

# ugly global variables!
# don't do this to much
# only tolerated here because we don't define any classes for the sake of
# readablitiy. this will be refactored in v0.2


nova, cinder, neutron = None, None, None


async def create_volume(cinder, image, zone, klass, size=25):
    bdm_v2 = {
        "boot_index": 0,
        "source_type": "volume",
        "volume_size": str(size),
        "destination_type": "volume",
        "delete_on_termination": True}

    v = cinder.volumes.create(size, name=uuid.uuid4(), imageRef=image.id,
                              availability_zone=zone,
                              volume_type=klass)

    while v.status != 'available':
        await asyncio.sleep(1)
        v = cinder.volumes.get(v.id)

    logger.debug("created volume %s %s" % (v, v.volume_type))

    if v.bootable != 'true':
        v.update(bootable=True)
        # wait for mark as bootable
        await asyncio.sleep(2)

    volume_data = copy.deepcopy(bdm_v2)
    volume_data['uuid'] = v.id

    return volume_data


async def create_instance_with_volume(name, zone, flavor, image,
                                      keypair, secgroups, userdata,
                                      hosts,
                                      nics=None,
                                      volume_klass=""
                                      ):
    global nova, neutron, cinder

    try:
        print(que("Checking if %s does not already exist" % name))
        server = nova.servers.find(name=name)
        ip = server.interface_list()[0].fixed_ips[0]['ip_address']
        print(info("This machine already exists ... skipping"))
        hosts[name] = (ip)
        return
    except NovaNotFound:
        print(info("Okay, launching %s" % name))
    except IndexError:
        logger.debug("Server found in weired state witout IP ... recreating")
        server.delete()

    volume_data = await create_volume(cinder, image, zone, volume_klass)

    try:
        print("Creating instance %s... " % name)
        instance = nova.servers.create(name=name,
                                       availability_zone=zone,
                                       image=None,
                                       key_name=keypair.name,
                                       flavor=flavor,
                                       nics=nics, security_groups=secgroups,
                                       block_device_mapping_v2=[volume_data],
                                       userdata=userdata,
                                       )

    except NovaClientException as E:
        print(info(red("Something weired happend, I so I didn't create %s" %
                       name)))
        print(info(yellow(E.message)))
        # TODO: clean volume and nic here
    except KeyboardInterrupt:
        print(info(red("Oky doky, stopping as you interrupted me ...")))
        print(info(red("Cleaning after myself")))
        # TODO: clean volume and nic here
        # clean volume
        cinder.volumes.delete(volume_data["id"])

    inst_status = instance.status
    print("waiting for 5 seconds for the machine to be launched ... ")
    await asyncio.sleep(5)

    while inst_status == 'BUILD':
        print("Instance: " + instance.name + " is in " + inst_status +
              " state, sleeping for 5 seconds more...")
        await asyncio.sleep(5)
        instance = nova.servers.get(instance.id)
        inst_status = instance.status

    print("Instance: " + instance.name + " is in " + inst_status + " state")

    ip = instance.interface_list()[0].fixed_ips[0]['ip_address']
    print("Instance booted! Name: " + instance.name + " Status: " +
          instance.status + ", IP: " + ip)

    hosts[name] = (ip)


def read_os_auth_variables(trim=True):
    """
    Automagically read all OS_* variables and
    yield key: value pairs which can be used for
    OS connection
    """
    d = {}
    for k, v in os.environ.items():
        if k.startswith("OS_"):
            d[k[3:].lower()] = v
    if trim:
        not_in_default_rc = ('interface', 'region_name',
                             'identity_api_version', 'endpoint_type',
                             )

        [d.pop(i) for i in not_in_default_rc if i in d]

    return d


def get_clients():
    try:
        auth = identity.Password(**read_os_auth_variables())
        sess = session.Session(auth=auth)
        nova = nvclient.Client('2.1', session=sess)
        neutron = ntclient.Client(session=sess)
        cinder = cclient.Client('3.0', session=sess)
    except TypeError:
        print(red("Did you source your OS rc file in v3?"))
        print(red("If your file has the key OS_ENDPOINT_TYPE it's the"
                  " wrong one!"))
        sys.exit(1)
    except KeyError:
        print(red("Did you source your OS rc file?"))
        sys.exit(1)

    return nova, neutron, cinder


def create_userdata(role, img_name, cluster_info=None,
                    cloud_provider=None,
                    cert_bundle=None, encryption_key=None,
                    **kwargs):
    """
    Create multipart userdata for Ubuntu
    """

    if 'ubuntu' in img_name.lower() and role == 'master':

        userdata = str(MasterInit(role, cluster_info, cert_bundle,
                                  encryption_key,
                                  cloud_provider, **kwargs))
    elif 'ubuntu' in img_name.lower() and role == 'node':
        kubelet_token = kwargs.get('kubelet_token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        service_account_bundle = kwargs.get('service_account_bundle')

        userdata = str(NodeInit(role, kubelet_token, ca_cert,
                                cert_bundle, service_account_bundle,
                                cluster_info, calico_token))
    else:
        userdata = """
                   #cloud-config
                   manage_etc_hosts: true
                   runcmd:
                    - swapoff -a
                   """
        userdata = textwrap.dedent(userdata).strip()
    return userdata


class NodeBuilder:

    def __init__(self, nova, neutron, config):
        logger.info(info(cyan(
            "gathering node information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, config)

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
                           no_cloud_init=False
                           ):
        node_args = {'kubelet_token': kubelet_token,
                     'cluster_info': etcd_host_list,
                     'calico_token': calico_token,
                     }

        if no_cloud_init:
            user_data = create_userdata('no-role', self._info.image.name,
                                        **node_args)
        else:
            node_args.update({'ca_cert': certs['ca'],
                              'service_account_bundle': certs[
                                  'service-account'],  # noqa
                              'cert_bundle': certs['k8s']})
            user_data = create_userdata('node', self._info.image.name,
                                        **node_args)

        task_args_node = self._info.node_args_builder(user_data, hosts)

        hosts = self._info.distribute_nodes()

        self._info.assign_nics_to_nodes(hosts, nics)
        volume_klass = self._info.storage_class
        loop = asyncio.get_event_loop()

        tasks = [loop.create_task(create_instance_with_volume(
            host.name, host.zone,
            nics=host.nic, volume_klass=volume_klass,
            *task_args_node))
            for host in hosts]

        return tasks


class ControlPlaneBuilder:

    def __init__(self, nova, neutron, config):

        logger.info(info(cyan(
            "gathering control plane information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, config)

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

        cloud_provider_info = OSCloudConfig(
            **read_os_auth_variables(trim=False))

        token_csv_data = get_token_csv(admin_token,
                                       calico_token,
                                       kubelet_token)

        master_args = dict(
            cloud_provider=cloud_provider_info,
            encryption_key=encryption_key,
            token_csv_data=token_csv_data,
            cluster_info=etcd_host_list,
        )

        if no_cloud_init:
            user_data = create_userdata('no-role', self._info.image.name,
                                        **master_args)
        else:
            master_args.update({'cert_bundle':
                                (certs['ca'], certs['k8s'],
                                 certs['service-account'])})
            user_data = create_userdata('master', self._info.image.name,
                                        **master_args)

        tasks_args_masters = self._info.node_args_builder(user_data, hosts)

        masters_zones = self._info.distribute_management()
        self._info.assign_nics_to_management(masters_zones, nics)

        volume_klass = self._info.storage_class
        loop = asyncio.get_event_loop()

        tasks = [loop.create_task(create_instance_with_volume(
            masters_zones[i].name, masters_zones[i].zone,
            nics=masters_zones[i].nic,
            volume_klass=volume_klass,
            *tasks_args_masters))
            for i in range(0, self._info.n_masters)]

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
                                          no_cloud_init=no_cloud_init)

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
            path = write_kubeconfig(config, etcd_host_list, admin_token,
                                    True)

            logger.info("Waiting for K8S API server to launch")

            manifest_path = os.path.join("kolt", "k8s-manifests")
            k8s = K8S(path, manifest_path)

            while not k8s.is_ready:
                logger.debug("Kubernetes API Server is still not ready ...")
                time.sleep(2)

            logger.debug("Kubernetes API Server is ready !!!")
            manifest_path = os.path.join("kolt", "k8s-manifests")

            # crate rbac realted stuff
            k8s.apply_roles()
            k8s.apply_role_bindings()
            # service accounts
            k8s.apply_service_accounts()
            # create calico configuration
            url = "https://" + str(etcd_host_list[0].ip_address) + \
                  ":" + str(etcd_host_list[0].port - 1)
            print("etcd_host fuer calico: {}".format(url))
            k8s.apply_calico_config_map(url)

            # create calico secrets
            k8s.apply_calico_secrets(b64_key(certs["k8s"].key),
                                     b64_cert(certs["k8s"].cert),
                                     b64_cert(certs["ca"].cert))

            k8s.apply_daemon_sets()
            k8s.apply_deployments()
            k8s.apply_services()

        if no_cloud_init:
            return create_inventory(hosts, config)


@mach1()
class Kolt:

    def __init__(self):

        global nova, neutron, cinder
        nova, neutron, cinder = get_clients()

    def certs(self, config, key=None, ca=None):
        """
        Create cluster certificates
        """
        if key and ca:
            ca_bundle = CertBundle.read_bundle(key, ca)
        else:
            ca_bundle = None

        names, ips = get_server_info_from_openstack(config, nova)
        create_certs(config, names, ips, ca_bundle=ca_bundle)

    def k8s(self, config):
        """
        Bootstrap a Kubernetes cluster

        config - configuration file
        inventory - invetory file to write
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        builder.run(config)

    def kubespray(self, config, inventory=None):
        """
        Launch machines on opentack and write a configuration for kubespray
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        builder = ClusterBuilder()
        cfg = builder.run(config, no_cloud_init=True)

        if inventory:
            with open(inventory, 'w') as f:
                cfg.write(f)
        else:
            print(info("Here is your inventory ..."))
            print(
                red(
                    "You can save this inventory to a file with the option -i"))  # noqa
            cfg.write(sys.stdout)

    def destroy(self, config):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.safe_load(stream)

        delete_cluster(config, nova, neutron)
        sys.exit(0)

    def oc(self, config, inventory=None):
        """
        Create OpenStack machines for Openshift installation with Ansible

        config - configuration file
        inventory - invetory file to write
        """
        print("Not implemented yet ...")


def main():
    k = Kolt()
    k.run()
