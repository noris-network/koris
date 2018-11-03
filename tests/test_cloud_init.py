import base64
import re
import uuid
from unittest.mock import patch
import yaml

import pytest

from kolt.provision.cloud_init import MasterInit, NodeInit
from kolt.ssl import create_certs, CertBundle, create_key, create_ca
from kolt.cloud.openstack import OSCloudConfig
from kolt.util.util import (get_kubeconfig_yaml,
                            get_token_csv)


class DummyServer:  # pylint: disable=too-few-public-methods
    """
    Mock an OpenStack server
    """
    def __init__(self, name, ip_address):
        self.name = name
        self.ip_address = ip_address


test_cluster = [DummyServer("master-%d-test" % i,
                            "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in etcd_host_list]))


with patch('kolt.cloud.openstack.read_os_auth_variables') as p:
    p.return_value = dict(username="kubepipeline", password="s9kr9t",
                          auth_url="keystone.myopenstack.de",
                          project_id="f4c0a6de561e487d8ba5d1cc3f1042e8",
                          domain_id="2a73b8f597c04551a0fdc8e95544be8a",
                          user_domain_name="noris.de",
                          region_name="de-nbg6-1")

    cloud_config = OSCloudConfig()


def create_etcd_certs(names, ips):
    _key = create_key(size=2048)
    _ca = create_ca(_key, _key.public_key(),
                    "DE", "BY", "NUE",
                    "Kubernetes", "CDA-PI",
                    "kubernetes")
    ca_bundle = CertBundle(_key, _ca)

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


certs = create_certs({}, hostnames, ips, write=False)
for item in create_etcd_certs(hostnames, ips):
    certs.update(item)

encryption_key = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()

admin_token = uuid.uuid4().hex[:32]
kubelet_token = uuid.uuid4().hex[:32]
calico_token = uuid.uuid4().hex[:32]
token_csv_data = get_token_csv(admin_token, calico_token, kubelet_token)


@pytest.fixture
def ci_master():
    ci = MasterInit('master-1-test', test_cluster,
                    certs,
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config)
    return ci


@pytest.fixture
def ci_node():
    ci = NodeInit(kubelet_token,
                  certs['ca'],
                  certs['k8s'],
                  certs['service-account'],
                  test_cluster,
                  calico_token,
                  "10.32.192.121",
                  cloud_provider=cloud_config
                  )
    return ci


def test_token_cvs(ci_master):

    token_csv = ci_master._get_token_csv()
    assert yaml.safe_load(token_csv)[0]['permissions'] == '0600'


def test_cloud_config(ci_master):

    _cloud_config = ci_master._get_cloud_provider()
    assert yaml.safe_load(_cloud_config)[0]['permissions'] == '0600'


def test_encryption_config(ci_master):

    _config = ci_master._get_encryption_config()

    _config = yaml.safe_load(_config)[0]

    assert _config['path'] == '/var/lib/kubernetes/encryption-config.yaml'

    content = _config['content']
    enc_ = yaml.safe_load(base64.b64decode(content).decode())
    assert enc_['resources'][0]['providers'][0][
        'aescbc']['keys'][0]['secret'] == encryption_key


def test_certificate_info(ci_master):

    certs_config = ci_master._get_certificate_info()

    assert 8 == len(yaml.safe_load(certs_config))


def test_cloud_init(ci_master):

    config = ci_master.get_files_config()
    config = yaml.safe_load(config)

    assert len(config['write_files']) == 14

    etcd_host = test_cluster[0]

    etcd_env = [i for i in config['write_files'] if
                i['path'] == '/etc/systemd/system/etcd.env'][0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, 2380),
        etcd_env['content'])


def test_node_init(ci_node):
    config = ci_node.get_files_config()
    config = yaml.safe_load(config)

    assert len(config['write_files']) == 9


def test_get_kube_config():

    kcy = get_kubeconfig_yaml("https://bar:2349", "kubelet", "12312aed321",
                              skip_tls=True,
                              encode=False)

    kcy_dict = yaml.safe_load(kcy)
    assert 'insecure-skip-tls-verify' not in kcy_dict['clusters'][0]['cluster']
