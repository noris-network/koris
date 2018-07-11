import re
import yaml

from kolt.cloud import CloudInit
from kolt.util import EtcdHost

test_cluster = [EtcdHost("master-%d-k8s" % i,
                         "10.32.192.10%d" % i) for i in range(1, 4)]


def test_cloud_init():
    ci = CloudInit("master", "master-1-k8s", test_cluster)

    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 4

    etcd_host = test_cluster[0]

    assert re.findall("%s=https://%s:%s" % (
        etcd_host.name, etcd_host.ip_address, etcd_host.port),
        config['write_files'][-1]['content'])
