import base64
import textwrap
import uuid

from ipaddress import IPv4Address


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


def get_token_csv(adminToken):
    """
    write the content of
    /var/lib/kubernetes/token.csv
    """

    content = """
    {adminToken},admin,admin,"cluster-admin,system:masters"
    {calicoToken},calico,calico,"cluster-admin,system:masters"
    {kubeletToken},kubelet,kubelet,"cluster-admin,system:masters"
    """.format(
        adminToken=adminToken,
        calicoToken=uuid.uuid4().hex[:32],
        kubeletToken=uuid.uuid4().hex[:32]
    )

    return base64.b64encode(textwrap.dedent(content).encode()).decode()
