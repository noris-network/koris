"""
deploy cluster service to kubernetes via the API server
"""
import logging
from functools import partial
import urllib3


from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

from koris.util.util import get_logger

LOGGER = get_logger(__name__, level=logging.DEBUG)


class K8S:
    """
    Deploy basic service to the cluster

    This class is responsible of starting the CNI layer (calico) and
    the DNS service (kube-dns)

    """
    def __init__(self, config, manifest_path=None):

        self.config = config
        if not manifest_path:
            manifest_path = resource_filename(Requirement.parse("koris"),
                                              'koris/deploy/manifests')

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

    def wait_for_all_masters_ready(self, n_masters):
        """
        If we find at least one node that has no Ready: True, return False.
        """
        count = 0
        cond = {'Ready': 'True'}
        while True:
            for item in self.client.list_node(pretty=True).items:
                if cond in [{c.type: c.status} for c in item.status.conditions]:
                    if 'master' in item.metadata.name:
                        count += 1
                        yield item.metadata.name, item.status.addresses[0].address
            if count == n_masters:
                raise StopIteration  # pylint: disable=stop-iteration-return
