# https://support.ultimum.io/support/solutions/articles/1000125460-python-novaclient-neutronclient-glanceclient-swiftclient-heatclient
# http://docs.openstack.org/developer/python-novaclient/ref/v2/servers.html
import argparse
import asyncio
import base64
import logging
import os
import uuid
import textwrap
import sys

import yaml

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
from .hue import red, info, que, lightcyan as cyan
from .ssl import CertBundle
from .util import (EtcdHost,
                   OSCloudConfig, OSClusterInfo,
                   get_server_info_from_openstack,
                   get_token_csv,
                   )

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)


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


async def create_instance_with_volume(name, zone, flavor, image,
                                      keypair, secgroups, userdata,
                                      hosts, nics=None):

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

    bdm_v2 = {
        "boot_index": 0,
        "source_type": "volume",
        "volume_size": "25",
        "destination_type": "volume",
        "delete_on_termination": True}

    try:
        v = cinder.volumes.create(12, name=uuid.uuid4(), imageRef=image.id,
                                  availability_zone=zone)

        while v.status != 'available':
            await asyncio.sleep(1)
            v = cinder.volumes.get(v.id)

        v.update(bootable=True)
        # wait for mark as bootable
        await asyncio.sleep(2)

        bdm_v2["uuid"] = v.id
        print("Creating instance %s... " % name)
        instance = nova.servers.create(name=name,
                                       availability_zone=zone,
                                       image=None,
                                       key_name=keypair.name,
                                       flavor=flavor,
                                       nics=nics, security_groups=secgroups,
                                       block_device_mapping_v2=[bdm_v2],
                                       userdata=userdata,
                                       )

    except NovaClientException as E:
        print(info(red("Something weired happend, I so I didn't create %s" %
                       name)))
    except KeyboardInterrupt:
        print(info(red("Oky doky, stopping as you interrupted me ...")))
        print(info(red("Cleaning after myself")))
        v.delete

    inst_status = instance.status
    print("waiting for 10 seconds for the machine to be launched ... ")
    await asyncio.sleep(10)

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


def create_nics(neutron, num, netid, security_groups):
    for i in range(num):
        yield neutron.create_port(
            {"port": {"admin_state_up": True,
                      "network_id": netid,
                      "security_groups": security_groups}})


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

        nics = list(create_nics(neutron,
                                self._info.n_nodes,
                                self._info.net['id'],
                                self._info.secgroups))

        ips = (nic['port']['fixed_ips'][0]['ip_address'] for nic in nics)
        return self._info.nodes_names, ips, nics

    def create_hosts_tasks(self, nics, hosts, certs,
                           kubelet_token,
                           calico_token,
                           etcd_host_list
                           ):
        node_args = {'kubelet_token': kubelet_token,
                     'ca_cert': certs['ca'],
                     'cert_bundle': certs['k8s'],
                     'cluster_info': etcd_host_list,
                     'calico_token': calico_token,
                     'service_account_bundle': certs['service-account']}

        user_data = create_userdata('node', self._info.image.name, **node_args)

        task_args_node = self._info.node_args_builder(user_data, hosts)

        # nodes_zones = self._info.distribute_nodes()

        # hosts = list(NodeZoneNic.hosts_distributor(nodes_zones))
        hosts = self._info.distribute_nodes()
        self._info.assign_nics_to_nodes(hosts, nics)

        loop = asyncio.get_event_loop()

        tasks = [loop.create_task(create_instance_with_volume(
                 host.name, host.zone,
                 nics=host.nic,
                 *task_args_node))
                 for host in hosts]

        return tasks


class ControlPlaneBuilder:

    def __init__(self, nova, neutron, config):

        logger.info(info(cyan(
            "gathering control plane information from openstack ...")))
        self._info = OSClusterInfo(nova, neutron, config)

    def get_hosts_info(self):
        nics = list(create_nics(neutron,
                                self._info.n_masters,
                                self._info.net['id'],
                                self._info.secgroups))

        ips = (nic['port']['fixed_ips'][0]['ip_address'] for nic in nics)

        return self._info.management_names, ips, nics

    def create_hosts_tasks(self, nics, hosts, certs,
                           kubelet_token,
                           calico_token,
                           etcd_host_list):
        # generate a random string
        # this should be the equal of
        # ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)

        encryption_key = base64.b64encode(
            uuid.uuid4().hex[:32].encode()).decode()

        cloud_provider_info = OSCloudConfig(
            **read_os_auth_variables(trim=False))

        admin_token = uuid.uuid4().hex[:32]
        token_csv_data = get_token_csv(admin_token,
                                       calico_token,
                                       kubelet_token)

        master_args = dict(
            cloud_provider=cloud_provider_info,
            cert_bundle=(certs['ca'], certs['k8s'],
                         certs['service-account']),
            encryption_key=encryption_key,
            token_csv_data=token_csv_data,
            cluster_info=etcd_host_list,
        )

        user_data = create_userdata('master', self._info.image.name,
                                    **master_args)

        tasks_args_masters = self._info.node_args_builder(user_data, hosts)

        masters_zones = self._info.distribute_management()

        self._info.assign_nics_to_management(masters_zones, nics)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(create_instance_with_volume(
                 masters_zones[i].name, masters_zones[i].zone,
                 nics=masters_zones[i].nic,
                 *tasks_args_masters))
                 for i in range(0, self._info.n_masters)]

        return tasks


class ClusterBuilder:

    def run(self, config):

        nb = NodeBuilder(nova, neutron, config)
        cpb = ControlPlaneBuilder(nova, neutron, config)
        logger.debug(info("Done collection infromation from OpenStack"))
        hosts, ips, nics = nb.get_nodes_info(nova, neutron, config)

        cp_hosts, cp_ips, cp_nics = cpb.get_hosts_info()

        etcd_host_list = [EtcdHost(host, ip) for (host, ip) in
                          zip(cpb._info.management_names,
                              [nic['port']['fixed_ips'][0]['ip_address']
                               for nic in cp_nics])]

        certs = create_certs(config,
                             list(cp_hosts) + list(hosts),
                             list(cp_ips) + list(ips))

        calico_token = uuid.uuid4().hex[:32]
        kubelet_token = uuid.uuid4().hex[:32]

        hosts = {}
        tasks = nb.create_hosts_tasks(nics, hosts, certs, kubelet_token,
                                      calico_token, etcd_host_list)
        logger.debug(info("Done creating nodes tasks"))
        cp_tasks = cpb.create_hosts_tasks(nics, hosts, certs,
                                          kubelet_token,
                                          calico_token,
                                          etcd_host_list)
        logger.debug(info("Done creating control plane tasks"))

        tasks = cp_tasks + tasks
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.wait(tasks))
        loop.close()


def main():  # pragma: no coverage
    global nova, neutron, cinder

    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="YAML configuration")
    parser.add_argument("--destroy", help="Delete cluster",
                        action="store_true")
    parser.add_argument("--certs", help="Create cluster CA and certs only",
                        action="store_true")

    parser.add_argument("--ca", help="CA to reuse")
    parser.add_argument("--key", help="CA key to reuse")

    args = parser.parse_args()

    if not args.config:
        parser.print_help()
        sys.exit(2)

    with open(args.config, 'r') as stream:
        config = yaml.load(stream)

    nova, neutron, cinder = get_clients()

    if args.certs:
        if args.key and args.ca:
            ca_bundle = CertBundle.read_bundle(args.key, args.ca)
        else:
            ca_bundle = None

        names, ips = get_server_info_from_openstack(config, nova)
        create_certs(config, names, ips, ca_bundle=ca_bundle)
        sys.exit(0)

    if args.destroy:
        delete_cluster(config, nova, neutron)
        sys.exit(0)

    if not (config['n-etcds'] % 2 and config['n-etcds'] > 1):
        print(red("You must have an odd number (>1) of etcd machines!"))
        sys.exit(2)

    builder = ClusterBuilder()
    builder.run(config)
    # create_machines(nova, neutron, cinder, config)
    print(info("Cluster successfully set up."))
