import base64
import re
import uuid
import yaml

from unittest.mock import patch
import pytest

from kolt.cloud_init import MasterInit, NodeInit
from kolt.kolt import create_certs
from kolt.cloud.os import OSCloudConfig
from kolt.util.util import (EtcdHost, get_kubeconfig_yaml,
                            get_token_csv)


test_cluster = [EtcdHost("master-%d-k8s" % i,
                         "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in etcd_host_list]))


with patch('kolt.cloud.os.read_os_auth_variables') as p:
    p.return_value = dict(username="serviceuser", password="s9kr9t",
                          auth_url="keystone.myopenstack.de",
                          project_id="c869168a828847f39f7f06edd7305637",
                          domain_id="2a73b8f597c04551a0fdc8e95544be8a",
                          user_domain_name="noris.de",
                          region_name="de-nbg6-1")

    cloud_config = OSCloudConfig()

certs = create_certs({}, hostnames, ips, write=False)

encryption_key = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()

admin_token = uuid.uuid4().hex[:32]
kubelet_token = uuid.uuid4().hex[:32]
calico_token = uuid.uuid4().hex[:32]
token_csv_data = get_token_csv(admin_token, calico_token, kubelet_token)


@pytest.fixture
def ci_master():
    ci = MasterInit(test_cluster,
                    cert_bundle=(certs['ca'],
                                 certs['k8s'],
                                 certs['service-account']),
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
                  calico_token
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

    assert 4 == len(yaml.safe_load(certs_config))


def test_cloud_init(ci_master):

    config = ci_master.get_files_config()
    config = yaml.safe_load(config)

    assert len(config['write_files']) == 10

    etcd_host = test_cluster[0]

    etcd_env = [i for i in config['write_files'] if
                i['path'] == '/etc/systemd/system/etcd.env'][0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, etcd_host.port),
        etcd_env['content'])


def test_node_init(ci_node):
    config = ci_node.get_files_config()
    config = yaml.safe_load(config)

    assert len(config['write_files']) == 8


def test_get_kube_config():

    kcy = get_kubeconfig_yaml("https://bar:2349", "kubelet", "12312aed321",
                              skip_tls=True,
                              encode=False)

    kcy_dict = yaml.safe_load(kcy)
    assert 'insecure-skip-tls-verify' not in kcy_dict['clusters'][0]['cluster']
