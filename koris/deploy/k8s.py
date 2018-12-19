"""
deploy cluster service to kubernetes via the API server
"""
import logging
from functools import partial
import urllib3


from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

# LOGGER = get_logger(__name__, level=logging.DEBUG)


class K8S:
    """
    Deploy basic service to the cluster

    This class is responsible of starting the CNI layer (calico) and
    the DNS service (kube-dns)

    """
    def __init__(self, config, manifest_path):

        self.config = config
        self.manifest_path = manifest_path
        self.get_manifest = partial(resource_filename, Requirement('koris'))
        k8sconfig.load_kube_config(config)
        self.client = k8sclient.CoreV1Api()

    @property
    def is_ready(self):
        """
        check if the API server is already available
        """
        logging.getLogger("urllib3").setLevel(logging.ERROR)
        try:
            k8sclient.apis.core_api.CoreApi().get_api_versions()
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return True
        except urllib3.exceptions.MaxRetryError:
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return False

    @property
    def masters_ready(self):
        """
        If we find at least one node that has no Ready: True, return False.
        """
        res = []
        for item in self.client.list_node(pretty=True).items:
            if {'Ready': 'True'} in [{c.type: c.status} for c
                                     in item.status.conditions]:
                res.append(True)
            else:
                res.append(False)
        return all(res)
