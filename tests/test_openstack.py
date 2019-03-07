# OpenStack Integration tests

import os
import pytest

from koris.cloud import OpenStackAPI
from koris.cloud.builder import get_clients
from koris.cloud.openstack import LoadBalancer

LB_NAME = os.getenv('LOADBALANCER_NAME', 'os-integration-test')
LB_NAME = LB_NAME.split('-lb')[0]
CONFIG = {
    'cluster-name': LB_NAME,
    "private_net": {
        "name": LB_NAME,
        "subnet": {
            "name": f"{LB_NAME}-subnet",
            "cidr": "192.168.0.0/24"
        }
    }
}

# Get an Connection object that can be used for all tests
@pytest.fixture
def get_connection():
    return OpenStackAPI.connect()


# Neutron client for compability
@pytest.fixture
def get_neturon():
    _, neutron, _ = get_clients()
    return neutron


@pytest.fixture
def api_objects(get_neturon, get_connection):
    return get_neturon, get_connection


# Returns a LoadBalancer
@pytest.fixture
def get_lb():
    return LoadBalancer(CONFIG)


def test_get_connection(get_connection):
    conn = get_connection
    assert conn is not None


def test_create_lb(api_objects, get_lb):
    neutron, conn = api_objects

    lb = get_lb
    assert lb is not None

    lb_created, fip = lb.create(neutron, conn)
    assert lb_created is not None
    assert fip is not None
    assert lb.name == LB_NAME

