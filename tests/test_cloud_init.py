import yaml

from kolt.cloud import CloudInit

# cluster_info is a dictionary with infromation about the
# etcd cluster
test_cluster = {"n01_ip": "10.32.192.101",
                "n02_ip": "10.32.192.101",
                "n03_ip": "10.32.192.103",
                "n01_name": "master-1-k8s",
                "n02_name": "master-2-k8s",
                "n03_name": "master-3-k8s"}


def test_cloud_init():
    ci = CloudInit("master", "master-1-k8s", test_cluster)

    config = ci.get_files_config()
    config = yaml.load(config)

    assert len(config['write_files']) == 4
