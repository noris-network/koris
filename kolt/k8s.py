import logging
import os
import urllib3
import yaml


from kubernetes import (client as k8sclient, config as k8sconfig)
from pkg_resources import resource_filename, Requirement

from .util import (get_logger)

logger = get_logger(__name__)

req = Requirement('kolt')


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
        logger.debug("Applying roles")
        client = k8sclient.RbacAuthorizationV1beta1Api()

        for file_ in ["cluster-role-controller", "cluster-role-node"]:

            with open(resource_filename(
                req,
                os.path.join(
                    self.manifest_path, 'calico', 'rbac',
                    '%s.yml' % file_))) as f:
                payload = yaml.safe_load(f)

                client.create_cluster_role(payload)

    def apply_role_bindings(self):
        client = k8sclient.RbacAuthorizationV1beta1Api()

        for file_ in ["role-binding-node", "role-binding-controller"]:

            with open(resource_filename(
                req,
                os.path.join(
                    self.manifest_path, 'calico', 'rbac',
                    '%s.yml' % file_))) as f:

                client.create_cluster_role_binding(yaml.safe_load(f))

    def apply_service_accounts(self):
        for file_ in ["calico/serviceaccount-controller",
                      "calico/serviceaccount-node",
                      "service_account_kube-dns"]:
            with open(
                resource_filename(
                    req,
                    os.path.join(
                        self.manifest_path,
                        '%s.yml' % file_))) as f:

                self.client.create_namespaced_service_account("kube-system",
                                                              yaml.safe_load(f))

    def apply_config_maps(self):
        logger.debug("Applying configmaps")
        with open(
            resource_filename(
                req,
                os.path.join(manifest_path, 'config_map_kube-dns.yml'))) as f: # noqa

            configmap = yaml.safe_load(f)
            self.client.create_namespaced_config_map("kube-system", configmap)

    def apply_calico_config_map(self, etcd_end_point):
        with open(
            resource_filename(
                req,
                os.path.join(self.manifest_path, 'calico', 'config-map.yml'))) as f: # noqa

            configmap = yaml.safe_load(f)

            configmap["data"]["etcd_endpoints"] = etcd_end_point

            self.client.create_namespaced_config_map("kube-system", configmap)

    def apply_calico_secrets(self, k8s_key, k8s_cert, ca_cert):
        with open(resource_filename(req,
                                    os.path.join(self.manifest_path,
                                                 'calico',
                                                 'secret.yml'))) as f:
            secret = yaml.safe_load(f)

        secret["data"]["etcd-key"] = k8s_key
        secret["data"]["etcd-cert"] = k8s_cert
        secret["data"]["etcd-ca"] = ca_cert
        self.client.create_namespaced_secret("kube-system", secret)

    def apply_daemon_sets(self):
        logger.debug("Applying daemonsets")
        client = k8sclient.ExtensionsV1beta1Api()

        with open(
            resource_filename(
                req,
                os.path.join(self.manifest_path,
                             'calico',
                             'daemonset.yml'))) as f:
            client.create_namespaced_daemon_set("kube-system", yaml.safe_load(f))  # noqa

    def apply_deployments(self):
        logger.debug("Applying deployments")
        client = k8sclient.ExtensionsV1beta1Api()

        for file_ in ["calico/deployment.yml", "deployment_kube-dns.yml"]:
            with open(
                resource_filename(
                    req,
                    os.path.join(self.manifest_path,
                                 file_))) as f:
                client.create_namespaced_deployment("kube-system", yaml.safe_load(f))  # noqa

    def apply_services(self):

        for file_ in ["service_kube-dns.yml"]:
            with open(
                resource_filename(
                    req,
                    os.path.join(self.manifest_path,
                                 file_))) as f:
                self.client.create_namespaced_service("kube-system", yaml.safe_load(f))  # noqa
