#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `colt` package."""

import pytest
import uuid
import yaml

from kolt.kolt import host_names
from kolt.util import get_kubeconfig_yaml


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
    master = host_names("master", config["n-masters"],config['cluster-name'])[0]
    masteruri = "http://%s:3210" % master

    username = 'admin'
    admin_token = uuid.uuid4().hex[:32]
    kubeconfig =  get_kubeconfig_yaml(masteruri, username, admin_token, encode=False)
    kcy = yaml.load(kubeconfig)
    assert kcy["clusters"][0]["cluster"]["server"] == masteruri
    assert kcy["users"][0]["name"] == "admin"
    assert kcy["users"][0]["user"]["token"] == admin_token
