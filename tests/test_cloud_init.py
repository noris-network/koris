"""
tests for koris.provision.cloud_init
"""
import base64
from unittest.mock import patch

import pytest

from koris.provision.cloud_init import NthMasterInit, NodeInit, FirstMasterInit
from koris.ssl import (create_certs, CertBundle, create_key, create_ca)
from koris.cloud.openstack import OSCloudConfig


class DummyServer:  # pylint: disable=too-few-public-methods
    """
    Mock an OpenStack server
    """
    def __init__(self, name, ip_address):
        self.name = name
        self.ip_address = ip_address


TEST_CLUSTER = [DummyServer("master-%d-test" % i,
                            "10.32.192.10%d" % i) for i in range(1, 4)]

ETCD_HOST_LISTS = TEST_CLUSTER

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in ETCD_HOST_LISTS]))


with patch('koris.cloud.openstack.read_os_auth_variables') as p:
    p.return_value = dict(username="kubepipeline", password="s9kr9t",
                          auth_url="keystone.myopenstack.de",
                          project_id="f4c0a6de561e487d8ba5d1cc3f1042e8",
                          domain_id="2a73b8f597c04551a0fdc8e95544be8a",
                          user_domain_name="noris.de",
                          region_name="de-nbg6-1")

    CLOUD_CONFIG = OSCloudConfig()
LB_IP = "10.32.192.121",


def create_etcd_certs(names, ips):
    """create certificated for dummy servers"""
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


CERTS = create_certs({}, hostnames, ips, write=False)
for item in create_etcd_certs(hostnames, ips):
    CERTS.update(item)


@pytest.fixture
def ci_nth_master():
    ci = NthMasterInit(CLOUD_CONFIG, create_key(),
                       koris_env={"a": "b"})
    return ci


@pytest.fixture
def ci_first_master():
    ci = FirstMasterInit(create_key(),
                         CERTS['ca'],
                         CLOUD_CONFIG,
                         koris_env={"a": "b"}
                         )
    return ci


@pytest.fixture
def ci_node():
    ci = NodeInit(
        CERTS['ca'].cert,
        CLOUD_CONFIG,
        LB_IP,
        "6443",
        "a73b8f597c04551a0fdc8e95544be8a",
        "discovery_hash"
    )
    return ci


def test_first_master(ci_first_master):
    ci = ci_first_master
    assert ci is not None

    with pytest.raises(ValueError):
        ci = FirstMasterInit(create_key(),
                             CERTS['ca'],
                             CLOUD_CONFIG,
                             koris_env={}
                             )


def test_cloud_config(ci_first_master):
    ci_first_master._write_cloud_config()
    cloud_config = ci_first_master._cloud_config_data['write_files'][-1]
    assert cloud_config['path'] == '/etc/kubernetes/cloud-config'


def test_bootstrap_script_first_master(ci_first_master):

    ci_first_master.add_bootstrap_script()
    assert len(ci_first_master._attachments) == 1
    filename = ci_first_master._attachments[0].get_filename()
    assert filename == 'bootstrap-k8s-master-ubuntu-16.04.sh'


def test_bootstrap_script_nth_master(ci_nth_master):

    ci_nth_master.add_bootstrap_script()
    assert len(ci_nth_master._attachments) == 1
    filename = ci_nth_master._attachments[0].get_filename()
    assert filename == 'bootstrap-k8s-nth-master-ubuntu-16.04.sh'


def test_cloud_init(ci_nth_master):

    assert 'ssh_authorized_keys' in ci_nth_master._cloud_config_data


def test_node_init(ci_node):
    ci_node._write_koris_env()


def test_node_has_cloud_init(ci_node):
    ci_node._write_cloud_config()
    cloud_config = ci_node._cloud_config_data['write_files'][-1]
    assert b'username' in base64.b64decode(cloud_config['content'])
    assert cloud_config['path'] == '/etc/kubernetes/cloud-config'
