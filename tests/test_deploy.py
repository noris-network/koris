from unittest.mock import MagicMock
import pytest

from koris.deploy.k8s import K8S


class Interface:

    def __init__(self, address):

        self.address = address


class Condition:

    def __init__(self, type_, status):
        self.type = type_
        self.status = status


class DummyResponse:

    def __init__(self, items):
        for idx, item in enumerate(items):
            item.status.conditions = [Condition('Ready', 'True')]
            item.status.addresses = [Interface('192.168.1.10%s' % str(idx + 1))]
            item.metadata.name = 'master-%s-test' % str(idx + 1)
        self.items = items


def list_nodes(*args, **kwargs):
    return DummyResponse([MagicMock(), MagicMock(), MagicMock()])


def list_nodes_only_one_ready(*args, **kwargs):
    resp = DummyResponse([MagicMock(), MagicMock(), MagicMock()])
    resp.items[2].status.conditions[0] = Condition('Ready', 'False')
    resp.items[1].status.conditions[0] = Condition('Ready', 'False')
    return resp


@pytest.fixture
def k8s():
    return K8S("tests/test-admin.conf")


# def test_all_masters_ready(monkeypatch, k8s):
#     monkeypatch.setattr(k8s.client, 'list_node', list_nodes)
#     assert len(list(k8s.wait_for_all_masters_ready(3))) == 3


# def test_all_masters__1_ready(monkeypatch, k8s):
#     monkeypatch.setattr(k8s.client, 'list_node', list_nodes_only_one_ready)
#     assert len(list(k8s.wait_for_all_masters_ready(3))) == 1
