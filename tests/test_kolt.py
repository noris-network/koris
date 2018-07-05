#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `colt` package."""

import pytest

from kolt._init import create_ca
from kolt.kolt import host_names


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
#def test_create_ca():

#    assert "key" in create_ca("8760h")


