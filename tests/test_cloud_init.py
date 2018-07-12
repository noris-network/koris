import re
import yaml

from kolt.cloud import CloudInit
from kolt.kolt import create_certs
from kolt.util import EtcdHost, EtcdCertBundle, ServiceAccountCertBundle


test_cluster = [EtcdHost("master-%d-k8s" % i,
                         "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster

hostnames, ips = map(list, zip(*[(i.name, i.ip_address) for
                                 i in etcd_host_list]))

(_, ca_cert, k8s_key, k8s_cert,
 svc_accnt_key, svc_accnt_cert) = create_certs({},
                                               hostnames, ips, write=False)
etcd_cert_bundle = EtcdCertBundle(ca_cert, k8s_key, k8s_cert)
svc_accnt_cert_bundle = ServiceAccountCertBundle(svc_accnt_key, svc_accnt_cert)


def test_cloud_init():
    ci = CloudInit("master", "master-1-k8s", test_cluster,
                   (etcd_cert_bundle, svc_accnt_cert_bundle))

    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 6

    etcd_host = test_cluster[0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, etcd_host.port),
        config['write_files'][-3]['content'])
