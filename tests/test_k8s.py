import pytest

from .testdata import ETCD_RESPONSE

from koris.deploy.k8s import parse_etcd_response

ETCD_PARSED_EXPECTED = {
    'master-1-ajk-test': {
        'ID': "c20d88bf2648e4ec",
        'clientURLs': ['https://10.32.192.66:2379'],
        'peerURLs': ['https://10.32.192.66:2380']},
    'master-2-ajk-test': {
        'ID': "ab26c92563699735",
        'clientURLs': ['https://10.32.192.57:2379'],
        'peerURLs': ['https://10.32.192.57:2380']},
    'master-3-ajk-test': {
        'ID': "4ca02bbc63bf1da0",
        'clientURLs': ['https://10.32.192.90:2379'],
        'peerURLs': ['https://10.32.192.90:2380']}}


def test_parse_etcd_response():
    resp_invalid = ["", None, [], {}]

    for resp in resp_invalid:
        with pytest.raises(ValueError):
            parse_etcd_response(resp)

    resp_invalid = str.replace(ETCD_RESPONSE, "master", "Asdasd")
    with pytest.raises(ValueError):
        parse_etcd_response(resp_invalid)

    assert parse_etcd_response(ETCD_RESPONSE) == ETCD_PARSED_EXPECTED


# (aknipping) If someone figures out how to mock this bloody
# kubernetes python client PLEASE let me know.
# def test_etcd_members_ips():
#     k8s = MagicMock()
#     k8s.api = PropertyMock(return_value=True)
#     k8s.etcd_members.side_effect = K8S.etcd_members

#     for ip in VALID_IPV4:
#         assert isinstance(k8s.etcd_members(k8s, "test", ip), dict)

#     for ip in INVALID_IPV4:
#         with pytest.raises(RuntimeError):
#             k8s.etcd_members("test", ip)
