import logging
import urllib3
import yaml


from kubernetes import (client as k8sclient, config as k8sconfig)


class K8S:

    def __init__(self, config, manifest_path):

        self.config = config
        self.manifest_path = manifest_path
        k8sconfig.load_kube_config(config)
        self.client = k8sclient.CoreV1Api()

    @property
    def is_ready(self):
        logging.getLogger("urllib3").setLevel(logging.ERROR)
        try:
            k8sclient.apis.core_api.CoreApi().get_api_versions()
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return True
        except urllib3.exceptions.MaxRetryError:
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return False

    def apply_roles(self):
        pass

    def apply_role_bindings(self):
        pass

    def apply_config_maps(self):
        pass

    def apply_daemon_sets(self):
        pass

    def apply_deployments(self):
        pass
