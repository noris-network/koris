"""
deploy cluster service to kubernetes via the API server
"""
import base64
from datetime import datetime, timedelta
import getpass
import json
import logging
import os
import random
import socket
import string
import subprocess as sp
import sys
import time
import urllib3

from pkg_resources import resource_filename, Requirement

from kubernetes import (client as k8sclient, config as k8sconfig)

from koris.ssl import read_cert, discovery_hash
from koris.util.util import get_logger, retry

if getattr(sys, 'frozen', False):
    MANIFESTSPATH = os.path.join(
        sys._MEIPASS,  # pylint: disable=no-member, protected-access
        'koris/deploy/manifests')
else:
    MANIFESTSPATH = resource_filename(Requirement.parse("koris"),
                                      'koris/deploy/manifests')

LOGGER = get_logger(__name__, level=logging.DEBUG)


def get_node_addr(addresses, addr_type):
    """
    Parse the address of the node

    Args:
        addresses (object) - instance of addresses returned from k8s API
        addr_type (str) - the address type
    """
    return [i.address for i in addresses if i.type == addr_type][0]


KUBE_VERSION = "1.12.5"
SFTPOPTS = ["-i /etc/ssh/ssh_host_rsa_key ",
            "-o StrictHostKeyChecking=no ",
            "-o ConnectTimeout=60"]
SSHOPTS = ["-l ubuntu "] + SFTPOPTS

MASTER_ADDER_DEPLOYMENT = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {
        "name": "master-adder",
        "labels": {
            "k8s-app": "master-adder"
        },
        "namespace": "kube-system"
    },
    "spec": {
        "replicas": 1,
        "selector": {
            "matchLabels": {
                "k8s-app": "master-adder"
            }
        },
        "template": {
            "metadata": {
                "labels": {
                    "k8s-app": "master-adder"
                }
            },
            "spec": {
                "containers": [
                    {"name": "master-adder",
                     "image": "oz123/koris-etcd:0.2",
                     "volumeMounts":
                     [{"mountPath": "/usr/local/bin/add-master-script",
                       "subPath": "add_master_script.sh",
                       "name": "add-master-script"},
                      {"mountPath": "/etc/kubernetes/cloud.config",
                       "subPath": "cloud.config",
                       "name": "cloud-config"},
                      {"mountPath": "/etc/kubernetes/admin.conf",
                       "subPath": "admin.conf",
                       "name": "admin-conf"},
                      {"mountPath": "/etc/kubernetes/pki/sa.key",
                       "subPath": "sa.key",
                       "name": "sa-key"},
                      {"mountPath": "/etc/kubernetes/pki/sa.pub",
                       "subPath": "sa.pub",
                       "name": "sa-pub"},
                      {"mountPath": "/etc/kubernetes/pki/ca.crt",
                       "subPath": "tls.crt",
                       "name": "cluster-ca"},
                      {"mountPath": "/etc/kubernetes/pki/ca.key",
                       "subPath": "tls.key",
                       "name": "cluster-ca-key"},
                      {"mountPath": "/etc/ssh/ssh_host_rsa_key",
                       "subPath": "ssh_host_rsa_key",
                       "name": "ssh-key"},
                      {"mountPath": "/etc/kubernetes/pki/etcd/peer.crt",
                       "subPath": "tls.crt",
                       "name": "etcd-peer"},
                      {"mountPath": "/etc/kubernetes/pki/etcd/peer.key",
                       "subPath": "tls.key",
                       "name": "etcd-peer-key"},
                      {"mountPath": "/etc/kubernetes/pki/etcd/ca.crt",
                       "subPath": "tls.crt",
                       "name": "etcd-ca"},
                      {"mountPath": "/etc/kubernetes/pki/etcd/ca.key",
                       "subPath": "tls.key",
                       "name": "etcd-ca-key"},
                      {"mountPath": "/etc/kubernetes/pki/front-proxy-ca.key",
                       "subPath": "tls.key",
                       "name": "front-proxy-key"},
                      {"mountPath": "/etc/kubernetes/pki/front-proxy-ca.crt",
                       "subPath": "tls.crt",
                       "name": "front-proxy-ca"}],
                     "args": ["1200"],
                     "command": ["sleep"],
                     "env": [{"value": "".join(SFTPOPTS), "name": "SFTPOPTS"},
                             {"value": "".join(SSHOPTS), "name": "SSHOPTS"},
                             {"value": KUBE_VERSION,
                              "name": "KUBE_VERSION"},
                             {"value": "/etc/kubernetes/pki/etcd/ca.crt",
                              "name": "ETCDCTL_CACERT"},
                             {"value": "/etc/kubernetes/pki/etcd/peer.crt",
                              "name": "ETCDCTL_CERT"},
                             {"value": "/etc/kubernetes/pki/etcd/peer.key",
                              "name": "ETCDCTL_KEY"},
                             {"value": "3",
                              "name": "ETCDCTL_API"}]}],
                "volumes": [
                    {"configMap": {"name": "add-master-script.sh",
                                   "defaultMode": 484},
                     "name": "add-master-script"},
                    {"name": "cloud-config",
                     "secret": {"secretName": "cloud.config"}},
                    {"name": "admin-conf", "secret": {"secretName": "admin.conf"}},
                    {"name": "sa-key", "secret": {"secretName": "sa-key"}},
                    {"name": "sa-pub", "secret": {"secretName": "sa-pub"}},
                    {"name": "cluster-ca", "secret": {"secretName": "cluster-ca"}},
                    {"name": "cluster-ca-key", "secret": {"secretName": "cluster-ca"}
                     },
                    {"name": "front-proxy", "secret": {"secretName": "front-proxy"}},
                    {"name": "etcd-peer", "secret": {"secretName": "etcd-peer"}},
                    {"name": "etcd-peer-key", "secret": {"secretName": "etcd-peer"}},
                    {"name": "etcd-ca", "secret": {"secretName": "etcd-ca"}},
                    {"name": "etcd-ca-key", "secret": {"secretName": "etcd-ca"}},
                    {"name": "ssh-key", "secret": {"secretName": "ssh-key",
                                                   "defaultMode": 384}},
                    {"name": "front-proxy-ca", "secret": {"secretName":
                                                          "front-proxy"}},
                    {"name": "front-proxy-key",
                     "secret": {"secretName": "front-proxy"}}]}}}}


MASTER_ADDER_WAIT_SSH_SECONDS = 60


def rand_string(num):
    """
    generate a random string of len num
    """
    return ''.join([
        random.choice(string.ascii_letters.lower() + string.digits)
        for n in range(num)])


def get_token_description():
    """create a description for the token"""

    description = "Bootstrap token generated by 'koris add' from {} on {}"

    return description.format('%s@%s' % (getpass.getuser(), socket.gethostname()),
                              datetime.now())


class K8S:  # pylint: disable=too-many-locals,too-many-arguments
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
        self.api = k8sclient.CoreV1Api()

    def get_bootstrap_token(self):
        """
        Generate a Bootstrap token
        """
        tid = rand_string(6)
        token_secret = rand_string(16)
        data = {'description': get_token_description(),
                'token-id': tid,
                'token-secret': token_secret,
                'expiration':
                datetime.strftime(datetime.now() + timedelta(hours=2),
                                  "%Y-%m-%dT%H:%M:%SZ"),
                'usage-bootstrap-authentication': 'true',
                'usage-bootstrap-signing': 'true',
                'auth-extra-groups':
                'system:bootstrappers:kubeadm:default-node-token', }

        for k, val in data.items():
            data[k] = base64.b64encode(val.encode()).decode()
        sec = k8sclient.V1Secret(data=data)
        sec.metadata = k8sclient.V1ObjectMeta(
            **{'name': 'bootstrap-token-%s' % tid, 'namespace': 'kube-system'})
        sec.type = 'bootstrap.kubernetes.io/token'

        self.api.create_namespaced_secret(namespace="kube-system", body=sec)
        return ".".join((tid, token_secret))

    @property
    def host(self):
        """retrieve the host or loadbalancer info"""
        return self.api.api_client.configuration.host

    @property
    def ca_info(self):
        """return a dict with the read ca and the discovery hash"""
        return {"ca_cert": self.ca_cert, "discovery_hash": self.discovery_hash}

    @property
    def ca_cert(self):
        """
        retrun the CA as b64 string
        """
        return read_cert(self.api.api_client.configuration.ssl_ca_cert)

    @property
    def discovery_hash(self):
        """
        calculate and return a discovery_hash based on the cluster CA
        """
        return discovery_hash(self.ca_cert)

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
                                        lb_inst
                                        ):
        """
        If we find at least one node that has no Ready: True, return False.
        """
        cond = {'Ready': 'True'}
        while len(lb_inst.members) < n_masters:
            for item in self.api.list_node(pretty=True).items:
                if cond in [{c.type: c.status} for c in item.status.conditions]:
                    if 'master' in item.metadata.name:
                        address = item.status.addresses[0].address
                        if address not in lb_inst.members:
                            lb_inst.add_member(lb_inst.pool,
                                               address)
                            LOGGER.info(
                                "Added member no. %d %s to the loadbalancer",
                                len(lb_inst.members), address)

    def run_add_script(self, pod, master_name, master_ip,
                       new_master_name, new_master_ip):
        """Execute the adding of a master inside a pod"""
        LOGGER.info("Extract current etcd cluster state...")

        etcd_cluster = self.etcd_cluster_status(pod, master_ip)
        cmd = ('kubectl exec -it %s -n kube-system -- /bin/bash -c '
               '"/usr/local/bin/add-master-script '
               '%s %s %s %s %s"' % (pod, new_master_name, new_master_ip,
                                    etcd_cluster, master_name, master_ip))
        kctl = sp.Popen(cmd, shell=True)
        kctl.communicate()
        if kctl.returncode:
            raise ValueError("Could execute the adder script in the adder pod!")

    def add_master(self, new_master_name, new_master_ip):
        """adds a master to the cluster"""
        try:
            nodes = self.api.list_node(pretty=True)
            nodes = [node for node in nodes.items if
                     'node-role.kubernetes.io/master' in node.metadata.labels]
        except urllib3.exceptions.MaxRetryError:
            LOGGER.warning(
                "Connection failed! Are you using the correct kubernetes context?")
            sys.exit(1)

        addresses = nodes[0].status.addresses
        master_ip = get_node_addr(addresses, "InternalIP")
        master_name = get_node_addr(addresses, "Hostname")
        podname = self.launch_master_adder()
        LOGGER.info("Executing adder script on new master node...")
        self.run_add_script(podname, master_name, master_ip, new_master_name,
                            new_master_ip)

    def launch_master_adder(self):
        """
        launch the add_master_deployment.

        Args:
            new_master_name (str): the new master's name
            new_master_ip (str): the new master's IP address

        Return:
            str: the pod name
        """
        kctl = sp.Popen("kubectl apply -f -", stdin=sp.PIPE, shell=True)
        kctl.communicate(json.dumps(MASTER_ADDER_DEPLOYMENT).encode())

        if kctl.returncode:
            raise ValueError("Could not apply master adder pod!")

        LOGGER.info("Waiting for the pod to run ...")
        result = self.api.list_namespaced_pod(
            "kube-system",
            label_selector='k8s-app=master-adder')

        while not result.items or result.items[0].status.phase != "Running":
            time.sleep(1)
            result = self.api.list_namespaced_pod(
                "kube-system",
                label_selector='k8s-app=master-adder')
        return result.items[0].metadata.name

    def validate_context(self, cloud_client):
        """
        validate that server that we are talking to via K8S API
        is also the cloud context we are using.

        Args:
            host (str): a load balancer or server name found the k8s context
            cloud_client (obj): an object capable of querying the cloud for the
               presence of host

        Return:
            bool
        """
        for item in cloud_client.load_balancer.load_balancers():
            if item.vip_address == self.host:
                return True

        return False

    @staticmethod
    @retry(ValueError)
    def etcd_cluster_status(podname, master_ip):
        """Query etcd cluster for the status string"""
        cmd = ("kubectl exec -it %s -n kube-system "
               "-- /bin/sh -c \"ETCDCTL_API=3 etcdctl "
               "--endpoints=https://%s:2379 member list -w json\" "
               "| jq -r -M --compact-output '[.members | .[] | "
               ".name + \"=\" + .peerURLs[0]] | join(\"=\")'" % (podname,
                                                                 master_ip))

        kctl = sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.PIPE)
        stdout, stderr = kctl.communicate()

        if kctl.returncode:
            LOGGER.info(stderr)
            LOGGER.info(stdout)
            raise ValueError("Could not extract current etcd cluster state!")

        lines = stdout.decode().strip().splitlines()
        if not lines:
            LOGGER.error("etcd cluster state in unexcepted format %s", lines)
            LOGGER.error(stderr)
            raise ValueError

        etcd_cluster = lines[0]
        LOGGER.info("Current etcd cluster state is: %s", etcd_cluster)

        return etcd_cluster
