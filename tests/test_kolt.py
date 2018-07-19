#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `colt` package."""

import pytest
import uuid

from kolt.kolt import host_names
from kolt.kolt import write_kubeconfig

from kolt.util import EtcdHost

test_cluster = [EtcdHost("master-%d-k8s" % i,
                         "10.32.192.10%d" % i) for i in range(1, 4)]

etcd_host_list = test_cluster


@pytest.fixture
def response():
    """Sample pytest fixture.

    See more at: http://doc.pytest.org/en/latest/fixture.html
    """
    # import requests
    # return requests.get('https://github.com/audreyr/cookiecutter-pypackage')


def test_content(response):
    """Sample pytest test function with the pytest fixture as an argument."""
    # from bs4 import BeautifulSoup
    # assert 'GitHub' in BeautifulSoup(response.content).title.string


def test_host_names():
    assert ["etcd-1-k8s", "etcd-2-k8s"] == host_names("etcd", 2, "k8s")


def test_kubeconfig():
    config = {
        "n-masters": 2,
        "cluster-name": "k8s",
    }
    username = 'master'
    admin_token = uuid.uuid4().hex[:32]
    kcy = write_kubeconfig(config, username, admin_token, write=True)
