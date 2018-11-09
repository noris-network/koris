#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `colt` package."""

import uuid
import yaml

from kolt.util.util import host_names
from kolt.util.util import get_kubeconfig_yaml

test_cluster = [("master-%d-k8s" % i,
                 "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster


def test_host_names():
    assert ["etcd-1-k8s", "etcd-2-k8s"] == host_names("etcd", 2, "k8s")


def test_kubeconfig():
    config = {
        "n-masters": 2,
        "cluster-name": "k8s",
    }
    master = host_names("master", config["n-masters"],
                        config['cluster-name'])[0]
    master_uri = "https://%s:6443" % master

    username = 'admin'
    admin_token = uuid.uuid4().hex[:32]
    kubeconfig = get_kubeconfig_yaml(master_uri, username, admin_token,
                                     encode=False, skip_tls=True)
    kcy = yaml.safe_load(kubeconfig)
    assert kcy["clusters"][0]["cluster"]["server"] == master_uri
    assert kcy["users"][0]["name"] == "admin"
    assert kcy["users"][0]["user"]["token"] == admin_token
