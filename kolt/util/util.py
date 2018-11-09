import base64
import copy
import logging
import textwrap
import time

from functools import lru_cache
from functools import wraps

import yaml


def get_logger(name, level=logging.INFO):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    # add ch to logger
    logger.addHandler(ch)
    return logger


encryption_config_tmpl = """
kind: EncryptionConfig
apiVersion: v1
resources:
  - resources:
      - secrets
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: %%ENCRYPTION_KEY%%
      - identity: {}
"""

kubeconfig = {'apiVersion': 'v1',
              'clusters': [
                  {'cluster': {'insecure-skip-tls-verify': True,
                               'server': '%%%%MASTERURI%%%',
                               'certificate-authority':
                               '/var/lib/kubernetes/ca.pem'},
                   'name': 'kubernetes'}],
              'contexts': [
                  {'context':
                      {'cluster': 'kubernetes',
                       'user': '%%%USERNAME%%%'},
                   'name': '%%%USERNAME%%%-context'}],
              'current-context': '%%%USERNAME%%%-context',
              'kind': 'Config',
              'users': [
                  {'name': '%%%USERNAME%%%',
                   'user': {'token': '%%%USERTOKEN%%%'}
                   }]
              }


def get_kubeconfig_yaml(master_uri, username, token,
                        skip_tls=False,
                        encode=True,
                        ca="/var/lib/kubernetes/ca.pem"):
    config = copy.deepcopy(kubeconfig)
    if skip_tls:
        config['clusters'][0]['cluster'].pop('insecure-skip-tls-verify')
        config['clusters'][0]['cluster']['server'] = master_uri
        config['clusters'][0]['cluster']['certificate-authority'] = ca
    else:
        config['clusters'][0]['cluster'].pop('server')

    config['contexts'][0]['name'] = "%s-context" % username
    config['contexts'][0]['context']['user'] = "%s" % username
    config['current-context'] = "%s-context" % username
    config['users'][0]['name'] = username
    config['users'][0]['user']['token'] = token

    yml_config = yaml.dump(config)

    if encode:
        yml_config = base64.b64encode(yml_config.encode()).decode()
    return yml_config


calicoconfig = {
    "name": "calico-k8s-network",
    "type": "calico",
    "datastore_type": "etcdv3",
    "log_level": "DEBUG",
    "etcd_endpoints": "",
    "etcd_key_file": "/var/lib/kubernetes/kubernetes-key.pem",
    "etcd_cert_file": "/var/lib/kubernetes/kubernetes.pem",
    "etcd_ca_cert_file": "/var/lib/kubernetes/ca.pem",
    "ipam": {
        "type": "calico-ipam",
        "assign_ipv4": "true",
        "assign_ipv6": "false",
        "ipv4_pools": ["10.233.0.0/16"]
    },
    "policy": {
        "type": "k8s"
    },
    "nodename": "__NODENAME__"  # <- This is replaced during boot
}

#    "kubernetes": {
#        "kubeconfig": "/etc/calico/kube/kubeconfig"
#    }


def get_token_csv(adminToken, calicoToken, kubeletToken):
    """
    write the content of
    /var/lib/kubernetes/token.csv
    """
    # TODO: check how to get this working ...
    # {bootstrapToken},kubelet,kubelet,10001,"system:node-bootstrapper"
    content = """
    {adminToken},admin,admin,"cluster-admin,system:masters"
    {calicoToken},calico,calico,"cluster-admin,system:masters"
    {kubeletToken},kubelet,kubelet,"cluster-admin,system:masters"
    """.format(
        adminToken=adminToken,
        calicoToken=calicoToken,
        kubeletToken=kubeletToken,
        bootstrapToken=kubeletToken
    )

    return base64.b64encode(textwrap.dedent(content).encode()).decode()


@lru_cache(maxsize=16)
def host_names(role, num, cluster_name):
    return ["%s-%s-%s" % (role, i, cluster_name) for i in
            range(1, num + 1)]


def retry(exceptions, tries=4, delay=3, backoff=2, logger=None):
    """
    Retry calling the decorated function using an exponential backoff.

    Args:
        exceptions: The exception to check. may be a tuple of
            exceptions to check.
        tries: Number of times to try (not retry) before giving up.
        delay: Initial delay between retries in seconds.
        backoff: Backoff multiplier (e.g. value of 2 will double the delay
            each retry).
        logger: Logger to use. If None, print.
    """
    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    msg = '{}, Retrying in {} seconds...'.format(e,
                                                                 int(mdelay))
                    if logger:
                        logger(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry
