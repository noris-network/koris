# https://support.ultimum.io/support/solutions/articles/1000125460-python-novaclient-neutronclient-glanceclient-swiftclient-heatclient
# http://docs.openstack.org/developer/python-novaclient/ref/v2/servers.html
import asyncio
import base64
import copy
import os
import uuid
import textwrap
import sys

import yaml

from mach import mach1
from novaclient import client as nvclient
from novaclient.exceptions import (NotFound as NovaNotFound,
                                   ClientException as NovaClientException)
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient

from keystoneauth1 import identity
from keystoneauth1 import session

from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

from .cli import (delete_cluster, create_certs,
                  write_kubeconfig)  # noqa
from .cloud import MasterInit, NodeInit
from .hue import red, info, que, lightcyan as cyan, yellow
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


def get_host_zones(hosts, zones):
    # brain fuck warning
    # this divides the lists of hosts into zones
    # >>> hosts
    # >>> ['host1', 'host2', 'host3', 'host4', 'host5']
    # >>> zones
    # >>> ['A', 'B']
    # >>> list(zip([hosts[i:i + n] for i in range(0, len(hosts), n)], zones)) # noqa
    # >>> [(['host1', 'host2', 'host3'], 'A'), (['host4', 'host5'], 'B')]  # noqa
    if len(zones) == len(hosts):
        return list(zip(hosts, zones))
    else:
        end = len(zones) + 1 if len(zones) % 2 else len(zones)
        host_zones = list(zip([hosts[i:i + end] for i in
                               range(0, len(hosts), end)],
                              zones))
        return distribute_hosts(host_zones)


# ugly global variables!
# don't do this to much
# only tolerated here because we don't define any classes for the sake of
# readablitiy. this will be refactored in v0.2

nova, cinder, neutron = None, None, None

def create_nic_for_machines(nova, neutron, machine_names, netid, secgroups):
    """
    for each none existing node in machine_names create a network interfaces
    """
    nodes = []
    ips = []
    nics = []
    
    for name in machine_names:
        try:
            print(que("Checking if %s does not already exist" % name))
            server = nova.servers.find(name=name)
            ip = server.interface_list()[0].fixed_ips[0]['ip_address']
            print(info("This machine already exists ... skipping"))

            ips.append(ip)
            port = server.interface_list()[0].to_dict()
            port['id'] = port['port_id']
            port['network_id'] = port['net_id']
            port = {'port': port}
        
        except NovaNotFound:
            print(info("Okay, launching %s" % name))
            port = neutron.create_port(
                {"port": {"admin_state_up": True,
                 "network_id": netid,
                 "security_groups": secgroups}})
            ips.append(port["port"]["fixed_ips"][0]["ip_address"])

        nics.append(port)
        nodes.append(name)

    return nodes, ips, nics

async def create_volume(cinder, image, zone, klass):

    bdm_v2 = {
        "boot_index": 0,
        "source_type": "volume",
        "volume_size": "25",
        "destination_type": "volume",
        "delete_on_termination": True}

    v = cinder.volumes.create(12, name=uuid.uuid4(), imageRef=image.id,
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
        calculate node names and zone,
        build nics
        """
        return create_nic_for_machines(nova, neutron, self._info.nodes_names,
                                       self._info.net["id"], 
                                       self._info.secgroups)

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
                              'service_account_bundle': certs['service-account'], # noqa
                              'cert_bundle': certs['k8s']})
            user_data = create_userdata('node', self._info.image.name,
                                        **node_args)

        task_args_node = self._info.node_args_builder(user_data, hosts)

        # nodes_zones = self._info.distribute_nodes()

        # hosts = list(NodeZoneNic.hosts_distributor(nodes_zones))
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
        return create_nic_for_machines(nova, neutron, 
                                       self._info.management_names, 
                                       self._info.net["id"], 
                                       self._info.secgroups)

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
        hosts, ips, nics = nb.get_nodes_info(nova, neutron, config)

        cp_hosts, cp_ips, cp_nics = cpb.get_hosts_info()

        etcd_host_list = [EtcdHost(host, ip) for (host, ip) in
                          zip(cpb._info.management_names,
                              [nic['port']['fixed_ips'][0]['ip_address']
                               for nic in cp_nics])]

        ips = list(cp_ips) + list(ips) + ['127.0.0.1', "10.32.0.1"]
        hosts = list(cp_hosts) + list(hosts) \
            + ["kubernetes.default",
               "kubernetes.default.svc.cluster.local"]
        certs = create_certs(config, hosts, ips)

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

        logger.debug(info("Done creating nodes tasks"))

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

            k8sconfig.load_kube_config(path)

            # TODO: polling until the kubernetes cluster is running
            #,currently, this is done externally via:
            # watch -n 1 kubectl --kubeconfig="koltdev-admin.conf" get nodes
            import pdb
            pdb.set_trace()

            # crate rbac realted stuff
            client = k8sclient.RbacAuthorizationV1beta1Api()

            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico', 'rbac',
                                                     'cluster-role-controller.yml')), "r") as f:
                client.create_cluster_role(yaml.load(f))

            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico', 'rbac',
                                                     'role-binding-controller.yml')),
                      "r") as f:
                client.create_cluster_role_binding(yaml.load(f))

            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico', 'rbac',
                                                     'cluster-role-node.yml')),
                      "r") as f:
                client.create_cluster_role(yaml.load(f))


            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico', 'rbac',
                                                     'role-binding-node.yml')),
                      "r") as f:
                client.create_cluster_role_binding(yaml.load(f))

            # service accounts
            client = k8sclient.CoreV1Api()
            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'serviceaccount-controller.yml')),
                      "r") as f:
                client.create_namespaced_service_account("kube-system", yaml.load(f))

            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'serviceaccount-node.yml')),
                      "r") as f:
                client.create_namespaced_service_account("kube-system", yaml.load(f))

            # create calico deployment
            client = k8sclient.CoreV1Api()
            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'config-map.yml')),
                      "r") as f:
                configmap = yaml.load(f)

                # TODO: make clean, we want to have the etcd client port here, not the etcd peer port!
                # therefore -1
                # Apart from this, we may want to specify more than one, separated by comma as
                # delimiter
                url = "https://"+str(etcd_host_list[0].ip_address)+":"+str(etcd_host_list[0].port-1)
                print("etcd_host fuer calico: {}".format(url))
                pdb.set_trace()

                configmap["data"]["etcd_endpoints"] = url

                client.create_namespaced_config_map("kube-system", configmap)

            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'secret.yml')),
                      "r") as f:
                secret = yaml.load(f)
                secret["data"]["etcd-key"] = b64_key(certs["k8s"].key)
                secret["data"]["etcd-cert"] = b64_cert(certs["k8s"].cert)
                secret["data"]["etcd-ca"] = b64_cert(certs["ca"].cert)

                client.create_namespaced_secret("kube-system", secret)

            client = k8sclient.ExtensionsV1beta1Api()
            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'daemonset.yml')),
                      "r") as f:
                client.create_namespaced_daemon_set("kube-system", yaml.load(f))


            with open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt', 'k8s-manifests', 'calico',
                                                     'deployment.yml')),
                      "r") as f:
                client.create_namespaced_deployment("kube-system", yaml.load(f))

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
            config = yaml.load(stream)

        builder = ClusterBuilder()
        builder.run(config)

    def kubespray(self, config, inventory=None):
        """
        Launch machines on opentack and write a configuration for kubespray
        """
        with open(config, 'r') as stream:
            config = yaml.load(stream)

        builder = ClusterBuilder()
        cfg = builder.run(config, no_cloud_init=True)

        if inventory:
            with open(inventory, 'w') as f:
                cfg.write(f)
        else:
            print(info("Here is your inventory ..."))
            print(
                red("You can save this inventory to a file with the option -i")) # noqa
            cfg.write(sys.stdout)

    def destroy(self, config):
        """
        Delete the complete cluster stack
        """
        with open(config, 'r') as stream:
            config = yaml.load(stream)

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
