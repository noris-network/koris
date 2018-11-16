"""Tests for the koris.ssl class functionality"""

from shutil import rmtree
from cryptography.x509.oid import ExtensionOID
from cryptography.x509 import DNSName, IPAddress
from koris.ssl import create_certs, read_cert


def test_sslcertcreation():
    """Test correct DNSNames and IPs in created ssl certs"""

    config = {
        "n-nodes": 3,
        "n-masters": 3,
        "keypair": "otiram",
        "availibility-zones": ['nbg6-1a', 'nbg6-1b'],
        "cluster-name": "test",
        "private_net": "test-net",
        "security_group": "test-group",
        "image": "ubuntu 16.04",
        "node_flavor": "ECS.C1.4-8",
        "master_flavor": "ECS.C1.4-8",
        "storage_class": "Fast"
    }
    ##########################################################
    # Variables for the whole test
    ##########################################################
    certificate_file_directory = 'certs-test'
    ssl_cert = "%s/kubernetes.pem" % (certificate_file_directory,)
    subject_alt_name_oid = ExtensionOID.SUBJECT_ALTERNATIVE_NAME

    ##########################################################
    # Create certificates for commonly used kubernetes names
    ##########################################################
    cluster_host_names = [
        "kubernetes.default", "kubernetes.default.svc.cluster.local",
        "kubernetes"]
    ips = ['127.0.0.1', "10.32.0.1"]
    create_certs(config, cluster_host_names, ips)

    ##########################################################
    # Test correct SSL connection for all given hostnames
    ##########################################################
    k8s_cert = read_cert(ssl_cert)
    sans = k8s_cert.extensions.get_extension_for_oid(subject_alt_name_oid)
    san_names = sans.value.get_values_for_type(DNSName)
    san_ips = [str(ip) for ip in sans.value.get_values_for_type(IPAddress)]

    ##########################################################
    # Cleanup
    ##########################################################
    rmtree(certificate_file_directory)

    ##########################################################
    # Assertions
    ##########################################################
    assert set(san_names).issuperset(set(cluster_host_names))
    assert set(san_ips).issuperset(set(ips))
