"""
deploy cluster service to kubernetes via the API server
"""
import logging
import os

import urllib3
import sys


from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

from koris.util.util import get_logger

if getattr(sys, 'frozen', False):
    MANIFESTSPATH = os.path.join(
        sys._MEIPASS,  # pylint: disable=no-member, protected-access
        'koris/deploy/manifests')
else:
    MANIFESTSPATH = resource_filename(Requirement.parse("koris"),
                                      'koris/deploy/manifests')

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
            manifest_path = MANIFESTSPATH
        self.manifest_path = manifest_path
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

    def add_all_masters_to_loadbalancer(self,
                                        n_masters,
                                        lb_inst,
                                        neutron_client
                                        ):
        """
        If we find at least one node that has no Ready: True, return False.
        """
        cond = {'Ready': 'True'}
        while len(lb_inst.members) < n_masters:
            for item in self.client.list_node(pretty=True).items:
                if cond in [{c.type: c.status} for c in item.status.conditions]:
                    if 'master' in item.metadata.name:
                        address = item.status.addresses[0].address
                        if address not in lb_inst.members:
                            lb_inst.add_member(neutron_client, lb_inst.pool,
                                               address)
                            LOGGER.info(
                                "Added member no. %d %s to the loadbalancer",
                                len(lb_inst.members), address)
