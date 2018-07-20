import base64
import re
import uuid
import yaml

from kolt.cloud import MasterInit, NodeInit
from kolt.kolt import create_certs
from kolt.util import (EtcdHost, get_kubeconfig_yaml,
                       OSCloudConfig, get_token_csv)


test_cluster = [EtcdHost("master-%d-k8s" % i,
                         "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in etcd_host_list]))


cloud_config = OSCloudConfig(username="serviceuser", password="s9kr9t",
                             auth_url="keystone.myopenstack.de",
                             project_id="c869168a828847f39f7f06edd7305637",
                             domain_id="2a73b8f597c04551a0fdc8e95544be8a",
                             user_domain_name="noris.de",
                             region_name="de-nbg6-1")


(ca_bundle, k8s_bundle,
 svc_accnt_bundle, admin_bundle,
    kubelet_bundle) = create_certs({}, hostnames, ips, write=False)

encryption_key = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()

admin_token = uuid.uuid4().hex[:32]
kubelet_token = uuid.uuid4().hex[:32]
calico_token = uuid.uuid4().hex[:32]
token_csv_data = get_token_csv(admin_token, calico_token, kubelet_token)


def test_token_cvs():

    ci = MasterInit("master", test_cluster,
                    cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config,
                    token_csv_data=token_csv_data)

    token_csv = ci._get_token_csv()
    assert yaml.load(token_csv)[0]['permissions'] == '0600'


def test_cloud_config():

    ci = MasterInit("master", test_cluster,
                    cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config,
                    token_csv_data=token_csv_data)

    _cloud_config = ci._get_cloud_provider()
    assert yaml.load(_cloud_config)[0]['permissions'] == '0600'


def test_encryption_config():

    ci = MasterInit("master", test_cluster,
                    cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config,
                    token_csv_data=token_csv_data)

    _config = ci._get_encryption_config()

    _config = yaml.load(_config)[0]

    assert _config['path'] == '/var/lib/kubernetes/encryption-config.yaml'

    content = _config['content']
    enc_ = yaml.load(base64.b64decode(content).decode())
    assert enc_['resources'][0]['providers'][0][
        'aescbc']['keys'][0]['secret'] == encryption_key


def test_certificate_info():

    ci = MasterInit("master", test_cluster,
                    cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config,
                    token_csv_data=token_csv_data)

    certs_config = ci._get_certificate_info()

    assert 4 == len(yaml.load(certs_config))


def test_cloud_init():
    ci = MasterInit("master", test_cluster,
                    cert_bundle=(ca_bundle, k8s_bundle, svc_accnt_bundle),
                    encryption_key=encryption_key,
                    cloud_provider=cloud_config)

    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 10

    etcd_host = test_cluster[0]

    etcd_env = [i for i in config['write_files'] if
                i['path'] == '/etc/systemd/system/etcd.env'][0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, etcd_host.port),
        etcd_env['content'])


def test_node_init():
    ci = NodeInit("node",
                  kubelet_token,
                  ca_bundle.cert,
                  k8s_bundle, test_cluster,
                  calico_token
                  )
    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 6


def test_get_kube_config():

    kcy = get_kubeconfig_yaml("https://foo:2349", "kubelet", "12312aed321",
                              skip_tls=True,
                              encode=False)

    kcy_dict = yaml.load(kcy)
    assert 'insecure-skip-tls-verify' not in kcy_dict['clusters'][0]['cluster']
