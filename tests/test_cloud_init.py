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

    cluster_info = ci._etcd_cluster_info().lstrip("\n")
    cluster_info = yaml.load(cluster_info[cluster_info.index("\n"):])["write_files"][0]

    assert cluster_info['path'] == "/etc/systemd/system/etcd.env"
    cluster_info_content = {k:v for k,v in
                           [item.split("=", 1) for item in
                            cluster_info["content"].split()]}

    cluster_info_content["NODE01_IP"] == test_cluster["n01_ip"]

    ci._get_certificate_info()
