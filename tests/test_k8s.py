import pytest
import copy

from unittest.mock import patch, MagicMock
from .testdata import VALID_IPV4, INVALID_IPV4, ETCD_RESPONSE

from koris.deploy.k8s import K8S

IP = "1.2.3.4"

@patch("kubernetes.config.load_kube_config")
def test_etcd_members_ips(k8sconfig):
    k8s = K8S("test")
    assert k8s

    for ip in VALID_IPV4:
        assert isinstance(k8s.etcd_members("test", ip), dict)

    for ip in INVALID_IPV4:
        with pytest.raises(RuntimeError):
            k8s.etcd_members("test", ip)

@patch("kubernetes.stream")
@patch("kubernetes.config.load_kube_config")
def test_etcd_members_ips(k8sconfig, k8sstream):
    k8s = K8S("test")
    assert k8s

    k8sstream.return_value = ETCD_RESPONSE
    assert isinstance(k8s.etcd_members("test", IP), dict)