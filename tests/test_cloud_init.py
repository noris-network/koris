import base64
import re
import uuid
import yaml

from kolt.cloud import CloudInit, NodeInit
from kolt.kolt import create_certs
from kolt.util import (EtcdHost,
                       OSCloudConfig)


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


(_, ca_cert, k8s_bundle,
 svc_accnt_bundle, admin_bundle) = create_certs({},
                                                hostnames,
                                                ips, write=False)

encryption_key = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()
kubelet_token = base64.b64encode(uuid.uuid4().hex[:32].encode()).decode()
calico_token = uuid.uuid4().hex[:32]


def test_cloud_init():
    ci = CloudInit("master", "master-1-k8s", test_cluster,
                   cert_bundle=(ca_cert, k8s_bundle, svc_accnt_bundle),
                   encryption_key=encryption_key,
                   cloud_provider=cloud_config)

    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 9

    etcd_host = test_cluster[0]

    etcd_env = [i for i in config['write_files'] if
                i['path'] == '/etc/systemd/system/etcd.env'][0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, etcd_host.port),
        etcd_env['content'])


def test_node_init():
    ci = NodeInit("node", "node-1-k8s",
                  kubelet_token,
                  ca_cert,
                  k8s_bundle, test_cluster,
                  calico_token
                  )
    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 6
