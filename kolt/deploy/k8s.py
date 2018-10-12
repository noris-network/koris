"""
deploy cluster service to kubernetes via the API server
"""
import logging
import os
from functools import partial
import urllib3
import yaml


from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

from kolt.util.util import (get_logger, retry)

LOGGER = get_logger(__name__)


class K8S:
    """
    Deploy basic service to the cluster

    This class is responsible of starting the CNI layer (calico) and
    the DNS service (kube-dns)

    """
    def __init__(self, config, manifest_path):

        self.config = config
        self.manifest_path = manifest_path
        self.get_manifest = partial(resource_filename, Requirement('kolt'))
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

    @retry(exceptions=OSError)
    def apply_calico(self, etcd_key, etcd_cert, k8s_ca, lb_url):
        """
        start a daemon set for CNI
        """
        self._calico_roles()
        self._calico_role_bindings()
        self._calico_config_map(lb_url)
        self._calico_service_accounts()
        self._calico_secrets(etcd_key, etcd_cert, k8s_ca)
        self._calico_daemon_set()
        self._calico_controller()

    @retry(exceptions=OSError)
    def apply_kube_dns(self):
        """
        apply all resources for kube-dns
        """
        self._kubedns_service_account()
        self._kube_dns_service()
        self._kube_dns_deployment()

    def _calico_roles(self):
        LOGGER.debug("Applying calico roles")
        client = k8sclient.RbacAuthorizationV1beta1Api()

        for file_ in ["cluster-role-controller", "cluster-role-node"]:
            with open(
                    self.get_manifest(
                        os.path.join(
                            self.manifest_path,
                            'calico', 'rbac', '%s.yml' % file_))) as fh:
                payload = yaml.safe_load(fh)

                client.create_cluster_role(payload)

    def _calico_role_bindings(self):
        client = k8sclient.RbacAuthorizationV1beta1Api()

        for file_ in ["role-binding-node", "role-binding-controller"]:
            with open(
                    self.get_manifest(
                        os.path.join(
                            self.manifest_path, 'calico', 'rbac',
                            '%s.yml' % file_))) as fh:

                client.create_cluster_role_binding(yaml.safe_load(fh))

    def _calico_service_accounts(self):
        for file_ in ["calico/serviceaccount-controller",
                      "calico/serviceaccount-node"]:
            with open(
                    self.get_manifest(
                        os.path.join(self.manifest_path,
                                     '%s.yml' % file_))) as fh:

                self.client.create_namespaced_service_account(
                    "kube-system", yaml.safe_load(fh))

    def _kubedns_service_account(self):
        LOGGER.debug("Applying kube-dns serviceaccount")
        for file_ in ["service_account_kube-dns"]:
            with open(
                    self.get_manifest(
                        os.path.join(self.manifest_path,
                                     '%s.yml' % file_))) as fh:

                self.client.create_namespaced_service_account(
                    "kube-system", yaml.safe_load(fh))

    def _kube_config_map(self):
        LOGGER.debug("Applying calico configmaps")
        with open(
                self.get_manifest(
                    os.path.join(
                        self.manifest_path, 'config_map_kube-dns.yml'))) as fh:

            configmap = yaml.safe_load(fh)
            self.client.create_namespaced_config_map("kube-system", configmap)

    def _calico_config_map(self, etcd_end_point):
        with open(
                self.get_manifest(
                    os.path.join(
                        self.manifest_path, 'calico', 'config-map.yml'))) as fh:  # noqa

            configmap = yaml.safe_load(fh)

            configmap["data"]["etcd_endpoints"] = etcd_end_point

            self.client.create_namespaced_config_map("kube-system", configmap)

    def _calico_secrets(self, k8s_key, k8s_cert, ca_cert):
        with open(self.get_manifest(
                os.path.join(self.manifest_path,
                             'calico', 'secret.yml'))) as fh:
            secret = yaml.safe_load(fh)

        secret["data"]["etcd-key"] = k8s_key
        secret["data"]["etcd-cert"] = k8s_cert
        secret["data"]["etcd-ca"] = ca_cert
        self.client.create_namespaced_secret("kube-system", secret)

    def _calico_daemon_set(self):
        LOGGER.debug("Applying calico daemonsets")
        client = k8sclient.ExtensionsV1beta1Api()

        with open(
                self.get_manifest(
                    os.path.join(self.manifest_path,
                                 'calico', 'daemonset.yml'))) as fh:
            client.create_namespaced_daemon_set("kube-system",
                                                yaml.safe_load(fh))

    def _calico_controller(self):
        LOGGER.debug("Applying calico controeller deployments")
        client = k8sclient.ExtensionsV1beta1Api()

        for file_ in ["calico/deployment.yml"]:
            with open(self.get_manifest(
                    os.path.join(self.manifest_path, file_))) as fh:
                client.create_namespaced_deployment("kube-system",
                                                    yaml.safe_load(fh))

    def _kube_dns_deployment(self):
        LOGGER.debug("Applying kube-dns deployments")
        client = k8sclient.ExtensionsV1beta1Api()

        for file_ in ["deployment_kube-dns.yml"]:
            with open(self.get_manifest(
                    os.path.join(self.manifest_path, file_))) as fh:
                client.create_namespaced_deployment("kube-system",
                                                    yaml.safe_load(fh))

    def _kube_dns_service(self):
        LOGGER.debug("Applying kube-dns service")
        for file_ in ["service_kube-dns.yml"]:
            with open(self.get_manifest(
                    os.path.join(self.manifest_path, file_))) as fh:
                self.client.create_namespaced_service("kube-system",
                                                      yaml.safe_load(fh))
