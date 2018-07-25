import base64
import copy
import textwrap

from functools import lru_cache
from ipaddress import IPv4Address

import yaml


class NodeZoneNic:

    """
    A Simple data class for holding information about a host
    """

    def __init__(self, name, zone, nic=None):
        self.name = name
        self.zone = zone
        self.nic = nic

    @classmethod
    def hosts_distributor(cls, hosts_zones):
        for item in hosts_zones:
            hosts, zone = item[0], item[1]
            for host in hosts:
                yield cls(host, zone, None)

    def __repr__(self):

        return "<%s@%s>" % (self.name, self.zone)


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
        return NodeZoneNic.hosts_distributor(host_zones)


class OSClusterInfo:

    def __init__(self, nova, neutron, config):
        self.keypair = nova.keypairs.get(config['keypair'])
        self.image = nova.glance.find_image(config['image'])
        self.node_flavor = nova.flavors.find(name=config['node_flavor'])
        secgroup = neutron.find_resource('security_group',
                                         config['security_group'])
        self.secgroups = [secgroup['id']]

        self.net = neutron.find_resource("network", config["private_net"])
        self.name = config['cluster-name']
        self.n_nodes = config['n-nodes']
        self.n_masters = config['n-masters']
        self.azones = config['availibility-zones']
        self.storage_class = config['storage_class']

    @property
    def nodes_names(self):
        return host_names("node", self.n_nodes, self.name)

    @property
    def management_names(self):
        return host_names("master", self.n_masters, self.name)

    def node_args_builder(self, user_data, hosts):

        return [self.node_flavor, self.image, self.keypair, self.secgroups,
                user_data, hosts]

    def distribute_management(self):
        return list(get_host_zones(self.management_names, self.azones))

    def distribute_nodes(self):
        return list(get_host_zones(self.nodes_names, self.azones))

    def assign_nics_to_management(self, management_zones, nics):
        for idx, nic in enumerate(nics):
            management_zones[idx].nic = [{'net-id': self.net['id'],
                                         'port-id': nic['port']['id']}]

    def assign_nics_to_nodes(self, nodes_zones, nics):
        for idx, nic in enumerate(nics):
            nodes_zones[idx].nic = [{'net-id': self.net['id'],
                                     'port-id': nic['port']['id']}]


class OSCloudConfig:

    def __init__(self, username, password, auth_url,
                 **kwargs):
        self.username = username
        self.password = password
        self.auth_url = auth_url
        self.__dict__.update(kwargs)
        self.tenant_id = self.project_id
        self.__dict__.pop('project_id')

    def __str__(self):
        return textwrap.dedent("""
        [Global]
        username=%s
        password=%s
        auth-url=%s
        tenant-id=%s
        domain-name=%s
        region=%s
        """ % (self.username, self.password, self.auth_url,
               self.tenant_id, self.user_domain_name,
               self.region_name)).lstrip()

    def __bytes__(self):
        return base64.b64encode(str(self).encode())


class EtcdHost:

    def __init__(self, name, ip_address, port=2380):
        self.name = name
        self.ip_address = IPv4Address(ip_address)
        self.port = port

    def _connection_uri(self):
        return "%s=https://%s:%d" % (self.name, self.ip_address, self.port)

    def __str__(self):
        return self._connection_uri()


encryption_config_tmpl = """
kind: EncryptionConfig
apiVersion: v1
resources:
  - resources:
      - secrets
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: %%ENCRYPTION_KEY%%
      - identity: {}
"""

kubeconfig = {'apiVersion': 'v1',
              'clusters': [
                  {'cluster': {'insecure-skip-tls-verify': True,
                               'server': '%%%%MASTERURI%%%',
                               'certificate-authority':
                               '/var/lib/kubernetes/ca.pem'},
                   'name': 'kubernetes'}],
              'contexts': [
                  {'context':
                      {'cluster': 'kubernetes',
                       'user': '%%%USERNAME%%%'},
                   'name': '%%%USERNAME%%%-context'}],
              'current-context': '%%%USERNAME%%%-context',
              'kind': 'Config',
              'users': [
                  {'name': '%%%USERNAME%%%',
                   'user': {'token': '%%%USERTOKEN%%%'}
                   }]
              }


def get_kubeconfig_yaml(master_uri, username, token,
                        skip_tls=False,
                        encode=True):
    config = copy.deepcopy(kubeconfig)
    if skip_tls:
        config['clusters'][0]['cluster'].pop('insecure-skip-tls-verify')
    config['clusters'][0]['cluster']['server'] = master_uri
    config['contexts'][0]['name'] = "%s-context" % username
    config['contexts'][0]['context']['user'] = "%s" % username
    config['current-context'] = "%s-context" % username
    config['users'][0]['name'] = username
    config['users'][0]['user']['token'] = token

    yml_config = yaml.dump(config)

    if encode:
        yml_config = base64.b64encode(yml_config.encode()).decode()
    return yml_config


calicoconfig = {
    "name": "calico-k8s-network",
    "type": "calico",
    "datastore_type": "etcdv3",
    "etcd_endpoints": "",
    "etcd_key_file": "/var/lib/kubernetes/kubernetes-key.pem",
    "etcd_cert_file": "/var/lib/kubernetes/kubernetes.pem",
    "etcd_ca_cert_file": "/var/lib/kubernetes/ca.pem",
    "ipam": {
        "type": "calico-ipam",
        "assign_ipv4": "true",
        "assign_ipv6": "false"
    },
    "policy": {
        "type": "k8s"
    },
    "kubernetes": {
        "kubeconfig": "/etc/calico/kube/kubeconfig"
    }
}


def get_node_info_from_openstack(config, nova, role):
    # find all servers in my cluster which are etcd or master
    cluster_suffix = "-%s" % config['cluster-name']

    servers = [server for server in nova.servers.list() if
               server.name.endswith(cluster_suffix)]

    servers = [server for server in servers if
               server.name.startswith(role)]

    assert len(servers)

    names = []
    ips = []

    for server in servers:
        names.append(server.name)
        ips.append(server.interface_list()[0].fixed_ips[0]['ip_address'])

    names.append("localhost")
    ips.append("127.0.0.1")

    return names, ips


def get_server_info_from_openstack(config, nova):
    # find all servers in my cluster which are etcd or master
    cluster_suffix = "-%s" % config['cluster-name']

    servers = [server for server in nova.servers.list() if
               server.name.endswith(cluster_suffix)]

    assert len(servers)

    names = []
    ips = []

    for server in servers:
        names.append(server.name)
        ips.append(server.interface_list()[0].fixed_ips[0]['ip_address'])

    names.append("localhost")
    ips.append("127.0.0.1")

    return names, ips


def get_token_csv(adminToken, calicoToken, kubeletToken):
    """
    write the content of
    /var/lib/kubernetes/token.csv
    """
    # TODO: check how to get this working ...
    # {bootstrapToken},kubelet,kubelet,10001,"system:node-bootstrapper"
    content = """
    {adminToken},admin,admin,"cluster-admin,system:masters"
    {calicoToken},calico,calico,"cluster-admin,system:masters"
    {kubeletToken},kubelet,kubelet,"cluster-admin,system:masters"
    """.format(
        adminToken=adminToken,
        calicoToken=calicoToken,
        kubeletToken=kubeletToken,
        bootstrapToken=kubeletToken
    )

    return base64.b64encode(textwrap.dedent(content).encode()).decode()


@lru_cache(maxsize=10)
def host_names(role, num, cluster_name):
    return ["%s-%s-%s" % (role, i, cluster_name) for i in
            range(1, num + 1)]
