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

from ipaddress import IPv4Address
from functools import lru_cache
import yaml

from novaclient import client as nvclient
from novaclient.exceptions import (NotFound as NovaNotFound,
                                   ClientException as NovaClientException)
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient

from keystoneauth1 import identity
from keystoneauth1 import session

from .cloud import CloudInit, NodeInit
from .hue import red, info, que, lightcyan as cyan
from .ssl import (create_key, read_cert, read_key,
                  create_ca,
                  write_key, write_cert, CertBundle)
from .util import (EtcdHost,
                   OSCloudConfig,
                   get_kubeconfig_yaml,
                   get_server_info_from_openstack,
                   get_token_csv
                   )


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
                                      keypair, secgroups, role, userdata,
                                      hosts, nics=None):

    global nova, neutron, cinder

    try:
        print(que("Checking if %s does not already exist" % name))
        server = nova.servers.find(name=name)
        ip = server.interface_list()[0].fixed_ips[0]['ip_address']
        print(info("This machine already exists ... skipping"))
        hosts[name] = (ip, role)
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

    except NovaClientException:
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

    hosts[name] = (ip, role)


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


def create_userdata(role, img_name, hostname, cluster_info=None,
                    cloud_provider=None,
                    cert_bundle=None, encryption_key=None,
                    **kwargs):
    """
    Create multipart userdata for Ubuntu
    """

    if 'ubuntu' in img_name.lower() and role == 'master':

        userdata = str(CloudInit(role, hostname, cluster_info, cert_bundle,
                                 encryption_key,
                                 cloud_provider, **kwargs))
    elif 'ubuntu' in img_name.lower() and role == 'node':
        token = kwargs.get('token')
        ca_cert = kwargs.get('ca_cert')
        calico_token = kwargs.get('calico_token')
        userdata = str(NodeInit(role, hostname, token, ca_cert,
                                cert_bundle, cluster_info, calico_token))
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


@lru_cache(maxsize=10)
def host_names(role, num, cluster_name):
    return ["%s-%s-%s" % (role, i, cluster_name) for i in
            range(1, num + 1)]


def create_machines(nova, neutron, cinder, config):

    print(info(cyan("gathering information from openstack ...")))
    keypair = nova.keypairs.get(config['keypair'])
    image = nova.glance.find_image(config['image'])
    master_flavor = nova.flavors.find(name=config['master_flavor'])
    node_flavor = nova.flavors.find(name=config['node_flavor'])
    secgroup = neutron.find_resource('security_group',
                                     config['security_group'])
    secgroups = [secgroup['id']]

    net = neutron.find_resource("network", config["private_net"])

    netid = net['id']

    nics_masters = list(create_nics(neutron,
                                    int(config['n-masters']),
                                    netid,
                                    secgroups))

    nics_nodes = list(create_nics(neutron,
                                  int(config['n-nodes']),
                                  netid,
                                  secgroups))

    cluster = config['cluster-name']

    masters = host_names("master", config["n-masters"], cluster)
    nodes = host_names("node", config["n-nodes"], cluster)

    etcd_host_list = [EtcdHost(host, ip) for (host, ip) in
                      zip(masters, [nic['port']['fixed_ips'][0]['ip_address']
                          for nic in nics_masters])]

    hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                     i in etcd_host_list]))

    hostnames.extend(nodes)
    ips.extend(IPv4Address(nic['port']['fixed_ips'][0]['ip_address'])
               for nic in nics_nodes)

    (ca_bundle, k8s_bundle,
     svc_accnt_bundle, admin_bundle,
     kubelet_bundle) = create_certs(config, hostnames, ips)

    # generate a random string
    # this should be the equal of
    # ENCRYPTION_KEY=$(head -c 32 /dev/urandom | base64)

    encryption_key = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()

    cloud_provider_info = OSCloudConfig(**read_os_auth_variables(trim=False))

    admin_token = uuid.uuid4().hex[:32]
    kubelet_token = uuid.uuid4().hex[:32]
    calico_token = uuid.uuid4().hex[:32]
    token_csv_data = get_token_csv(admin_token, kubelet_token)

    # TODO: we don't use host name anywhere in CloudInit and NodeInit
    # we should refactor this out ...
    master_user_data = [
        create_userdata('master', config['image'], master, etcd_host_list,
                        cloud_provider=cloud_provider_info,
                        cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                        encryption_key=encryption_key,
                        token_csv_data=token_csv_data)
        for master in masters]

    node_args = {'token': kubelet_token, 'ca_cert': ca_bundle.cert,
                 'cert_bundle': kubelet_bundle,
                 'cluster_info': etcd_host_list,
                 'calico_token': calico_token}

    # TODO: we don't use host name anywhere in CloudInit and NodeInit
    # we should refactor this out ...
    node_user_data = [
        create_userdata('node', config['image'], node, **node_args)
        for node in nodes
    ]

    print(info(cyan("got my info, now launching machines ...")))

    hosts = {}

    build_args_master = [
        [master_flavor, image, keypair, secgroups, "master",
         master_user_data[i], hosts]
        for i in range(0, config['n-masters'])
    ]

    build_args_node = [
        [node_flavor, image, keypair, secgroups, "node",
         node_user_data[i], hosts]
        for i in range(0, config['n-nodes'])
    ]

    masters_zones = list(get_host_zones(masters, config['availibity-zones']))
    nodes_zones = list(get_host_zones(nodes, config['availibity-zones']))
    loop = asyncio.get_event_loop()

    for idx, nic in enumerate(nics_masters):
        masters_zones[idx][-1] = [{'net-id': net['id'],
                                   'port-id': nic['port']['id']}]

    for idx, nic in enumerate(nics_nodes):
        nodes_zones[idx][-1] = [{'net-id': net['id'],
                                 'port-id': nic['port']['id']}]

    tasks = [loop.create_task(create_instance_with_volume(
                              masters_zones[i][0],
                              masters_zones[i][1], nics=masters_zones[i][2],
             *(build_args_master[i])))
             for i in range(0, config['n-masters'])]

    tasks.extend([loop.create_task(create_instance_with_volume(
                  nodes_zones[i][0], nodes_zones[i][1], nics=nodes_zones[i][2],
                  *(build_args_node[i])))
                  for i in range(0, config['n-nodes'])])

    loop.run_until_complete(asyncio.wait(tasks))
    loop.close()


def delete_cluster(config):
    print(red("You are about to destroy your cluster!!!"))
    print(red("Are you really sure ? [y/N]"))
    ans = input(red("ARE YOU REALLY SURE???"))

    if ans.lower() == 'y':
        cluster_suffix = "-%s" % config['cluster-name']
        servers = [server for server in nova.servers.list() if
                   server.name.endswith(cluster_suffix)]

        async def del_server(server):
            await asyncio.sleep(1)
            nics = [nic for nic in server.interface_list()]
            server.delete()
            [neutron.delete_port(nic.id) for nic in nics]
            print("deleted %s ..." % server.name)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(del_server(server)) for server in servers]

        if tasks:
            loop.run_until_complete(asyncio.wait(tasks))
        loop.close()
    else:
        sys.exit(1)


def create_certs(config, names, ips, write=True, ca_bundle=None):
    """
    create new certificates, useful for replacing certificates
    and later for adding nodes ...
    """
    country = "DE"
    state = "Bayern"
    location = "NUE"

    if not ca_bundle:
        ca_key = create_key()
        ca_cert = create_ca(ca_key, ca_key.public_key(), country,
                            state, location, "Kubernetes", "CDA\PI",
                            "kubernetes")
        ca_bundle = CertBundle(ca_key, ca_cert)

    else:
        ca_key = ca_bundle.key
        ca_cert = ca_bundle.cert

    k8s_bundle = CertBundle.create_signed(ca_key,
                                          country,
                                          state,
                                          location,
                                          "Kubernetes",
                                          "CDA\PI",
                                          "kubernetes",
                                          names,
                                          ips)

    svc_accnt_bundle = CertBundle.create_signed(ca_key,
                                                country,
                                                state,
                                                location,
                                                "Kubernetes",
                                                "CDA\PI",
                                                name="service-accounts",
                                                hosts="",
                                                ips="")

    admin_bundle = CertBundle.create_signed(ca_key,
                                            country,
                                            state,
                                            location,
                                            "system:masters",
                                            "CDA\PI",
                                            name="admin",
                                            hosts="",
                                            ips=""
                                            )

    kubelet_bundle = CertBundle.create_signed(ca_key,
                                              country,
                                              state,
                                              location,
                                              "system:masters",
                                              "CDA\PI",
                                              name="kubelet",
                                              hosts=names,
                                              ips=ips
                                              )

    nodes = []
    node_bundles = []
    node_ip = None
    # todo: add node_ip
    for node in nodes:
        node_bundles.append(CertBundle.create_signed(ca_key,
                                                     country,
                                                     state,
                                                     location,
                                                     "system:nodes",
                                                     "CDA\PI",
                                                     name="system:node:%s" % node,  # noqa
                                                     hosts=[node],
                                                     ips=[node_ip]))

    if write:  # pragma: no coverage
        cert_dir = "-".join(("certs", config["cluster-name"]))

        if not os.path.exists(cert_dir):
            os.mkdir(cert_dir)

        write_key(ca_key, filename=cert_dir + "/ca-key.pem")
        write_cert(ca_cert, cert_dir + "/ca.pem")

        k8s_bundle.save("kubernetes", cert_dir)
        svc_accnt_bundle.save("service-account", cert_dir)
        admin_bundle.save("admin", cert_dir)
        kubelet_bundle.save("kubelet", cert_dir)

    return (ca_bundle, k8s_bundle,
            svc_accnt_bundle, admin_bundle, kubelet_bundle)


def write_kubeconfig(config, etcd_cluster_info, admin_token, write=False):
    master = host_names("master", config["n-masters"],
                        config['cluster-name'])[0]
    username = "admin"
    master_uri = "http://%s:3210" % master
    kubeconfig = get_kubeconfig_yaml(master_uri, username, admin_token, write,
                                     encode=False)
    if write:
        filename = "admin.conf"
        with open(filename, "w") as f:
            f.write(kubeconfig)


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
        delete_cluster(config)
        sys.exit(0)

    if not (config['n-etcds'] % 2 and config['n-etcds'] > 1):
        print(red("You must have an odd number (>1) of etcd machines!"))
        sys.exit(2)

    create_machines(nova, neutron, cinder, config)
    print(info("Cluster successfully set up."))
