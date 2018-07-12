from ipaddress import IPv4Address


class EtcdHost:

    def __init__(self, name, ip_address, port=2380):
        self.name = name
        self.ip_address = IPv4Address(ip_address)
        self.port = port

    def _connection_uri(self):
        return "%s=https://%s:%d" % (self.name, self.ip_address, self.port)

    def __str__(self):
        return self._connection_uri()


class CertBundle:

    def __init__(self, key, cert):
        self.key = key
        self.cert = cert


class EtcdCertBundle(CertBundle):

    def __init__(self, ca_cert, k8s_key, k8s_cert):
        super().__init__(k8s_key, k8s_cert)
        self.ca_cert = ca_cert


class ServiceAccountCertBundle(CertBundle):

    def __init__(self, key, cert):
        super().__init__(key, cert)


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


def get_etcd_info_from_openstack(config, nova):
    # find all servers in my cluster which are etcd or master
    cluster_suffix = "-%s" % config['cluster-name']

    servers = [server for server in nova.servers.list() if
               server.name.endswith(cluster_suffix)]
    # TODO: remove this crappy filter in the future
    # because we might want to put etcd on own servers
    servers = [server for server in servers if
               server.name.startswith("master")]

    assert len(servers)

    names = []
    ips = []

    for server in servers:
        names.append(server.name)
        ips.append(server.interface_list()[0].fixed_ips[0]['ip_address'])

    names.append("localhost")
    ips.append("127.0.0.1")

    return names, ips
