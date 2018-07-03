#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `colt` package."""

import pytest


from kolt._init import create_ca, get_ca_config


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


def test_create_ca():

    assert "key" in create_ca("8760h")


def test_get_ca_config():
    ca_config = get_ca_config("8760h")

    assert ca_config["signing"]["default"]["expiry"] == "8760h"
    assert ca_config["signing"]["profiles"]["expiry"] == "8760h"
