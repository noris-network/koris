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


test_cluster = [DummyServer("master-%d-test" % i,
                            "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in etcd_host_list]))


with patch('koris.cloud.openstack.read_os_auth_variables') as p:
    p.return_value = dict(username="kubepipeline", password="s9kr9t",
                          auth_url="keystone.myopenstack.de",
                          project_id="f4c0a6de561e487d8ba5d1cc3f1042e8",
                          domain_id="2a73b8f597c04551a0fdc8e95544be8a",
                          user_domain_name="noris.de",
                          region_name="de-nbg6-1")

cloud_config = OSCloudConfig()
lb_ip = "10.32.192.121",


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


@pytest.fixture
def ci_nth_master():
    ci = NthMasterInit(create_key())
    return ci


@pytest.fixture
def ci_first_master():
    ci = FirstMasterInit(create_key(),
                         certs['ca'],
                         cloud_config,
                         hostnames,
                         ips,
                         lb_ip,
                         "6443",
                         "bootstrap_token"
                         )
    return ci


@pytest.fixture
def ci_node():
    ci = NodeInit(
        certs['ca'],
        lb_ip,
        "6443",
        "a73b8f597c04551a0fdc8e95544be8a",
        "discovery_hash"
    )
    return ci


def test_cloud_config(ci_first_master):
    ci_first_master._write_cloud_config()
    cloud_config = ci_first_master._cloud_config_data['write_files'][-1]
    assert cloud_config['path'] == '/etc/kubernetes/cloud.config'


def test_cloud_init(ci_nth_master):

    assert 'ssh_authorized_keys' in ci_nth_master._cloud_config_data


def test_node_init(ci_node):
    ci_node._write_koris_env()
