# OpenStack Integration tests

import os
import pytest

from koris.cloud import OpenStackAPI
from koris.cloud.builder import get_clients
from koris.cloud.openstack import LoadBalancer, OSNetwork, OSSubnet, OSRouter

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
_, NEUTRON, _ = get_clients()

# Below, needs OS_ environment variables passed
# or functions need to be changed to use `conn`
NET = OSNetwork(NEUTRON, CONFIG).get_or_create()
SUBNET = OSSubnet(NEUTRON, NET['id'], CONFIG).get_or_create()
OSRouter(NEUTRON, NET['id'], SUBNET, CONFIG).get_or_create()


# Get an Connection object that can be used for all tests
@pytest.fixture
def get_connection():
    return OpenStackAPI.connect()


# Returns a LoadBalancer
@pytest.fixture
def get_lb():
    return LoadBalancer(CONFIG)


def test_get_connection(get_connection):
    conn = get_connection
    assert conn is not None


def test_create_lb(get_connection, get_lb):
    conn = get_connection

    lb = get_lb
    assert lb is not None

    lb_created, fip = lb.create(NEUTRON, conn)
    assert lb_created is not None
    assert fip is not None
    assert lb.name == LB_NAME

