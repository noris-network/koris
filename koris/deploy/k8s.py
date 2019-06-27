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
import re
import socket
import string
import subprocess as sp
import sys
import time
import urllib3

from pkg_resources import resource_filename, Requirement
from netaddr import valid_ipv4

from kubernetes import client as k8sclient
from kubernetes.stream import stream
from kubernetes.client.rest import ApiException
from kubernetes.client import api_client
from kubernetes.client.configuration import Configuration
from kubernetes.config import kube_config
from kubernetes.utils import create_from_yaml

import yaml

from koris import KUBERNETES_BASE_VERSION
from koris.ssl import read_cert
from koris.ssl import discovery_hash as ssl_discovery_hash
from koris.util.util import retry
from koris.util.logger import Logger
from koris import MASTER_LISTENER_NAME

if getattr(sys, 'frozen', False):
    MANIFESTSPATH = os.path.join(
        sys._MEIPASS,  # pylint: disable=no-member, protected-access
        'koris/deploy/manifests')
else:
    MANIFESTSPATH = resource_filename(Requirement.parse("koris"),
                                      'koris/deploy/manifests')

LOGGER = Logger(__name__)


def _get_node_addr(addresses, addr_type):
    """
    Parse the address of the node

    Args:
        addresses (object) - instance of addresses returned from k8s API
        addr_type (str) - the address type
    """
    return [i.address for i in addresses if i.type == addr_type][0]


SFTPOPTS = ["-i /etc/ssh/ssh_host_rsa_key ",
            "-o StrictHostKeyChecking=no ",
            "-o ConnectTimeout=60"]
SSHOPTS = ["-l ubuntu "] + SFTPOPTS

# The deployment configuration of the master-adder operator.
# This pod runs inside a cluster and waits for requests to bootstrap new masters
MASTER_ADDER_PODNAME = "master-adder"
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
                "nodeSelector": {"node-role.kubernetes.io/master": ""},
                "tolerations": [{"key": "node-role.kubernetes.io/master",
                                 "effect": "NoSchedule"}],
                "containers": [
                    {"name": MASTER_ADDER_PODNAME,
                     "image": "oz123/koris-etcd:0.3",
                     "volumeMounts":
                     [{"mountPath": "/usr/local/bin/add-master-script",
                       "subPath": "add_master_script.sh",
                       "name": "add-master-script"},
                      {"mountPath": "/etc/kubernetes/audit-policy.yml",
                       "subPath": "audit-policy.yml",
                       "name": "audit-policy"},
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
                             {"value": None,
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
                    {"configMap": {"name": "audit-policy",
                                   "defaultMode": 420},
                     "name": "audit-policy"},
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


def parse_etcd_response(resp):
    """Takes a response from etcdctl and parses it for its member info.

    The response is to be expected in JSON format as obtained by
    ``etcdctl member list -w json``. Right now, the IDs in the JSON
    response are in uint64 format and will be transformed into hex
    with this function.

    Args:
        resp (str): A JSON response from etcdctl.

    Returns:
        A dict containing member information.

    Raises:
        ValueError if state could not be extracted.
    """

    if not resp or resp is None:
        raise ValueError("etcdtl response is empty")

    if not re.search("master-\\d+", resp):
        LOGGER.debug(resp)
        raise ValueError("can't find 'master' in etcdtl response")

    # Reconstructing the response so we get a dict where the key is the
    # member name and and value is a dict with the other info.
    out = {}
    resp_yaml = yaml.load(resp)
    for mem in resp_yaml['members']:
        out[mem['name']] = {k: v for k, v in mem.items() if k != "name"}

        # ID is uint64, but we need it in hex
        out[mem['name']]['ID'] = hex(out[mem['name']]['ID'])[2:]

    return out


class K8S:  # pylint: disable=too-many-locals,too-many-arguments
    """Class allowing various interactions with a Kubernets cluster.

    Args:
        config (str): File path for the kubernetes configuration file
        manfiest_path (str): Path for kubernetes manifests to be applied
    """

    def __init__(self, config, manifest_path=None):

        self.config = config
        if not manifest_path:
            manifest_path = MANIFESTSPATH
        self.manifest_path = manifest_path
        kube_config.load_kube_config(config_file=config)
        config = Configuration()
        self.api = k8sclient.CoreV1Api()
        self.client = api_client.ApiClient(configuration=config)

    def get_bootstrap_token(self):
        """Generate a Bootstrap token

        Returns:
            A string of the form ``<token id>.<token secret>``.
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
        """Retrieve the host or loadbalancer info"""
        return self.api.api_client.configuration.host

    @property
    def ca_info(self):
        """Return a dict with the read ca and the discovery hash"""
        return {"ca_cert": self.ca_cert, "discovery_hash": self.discovery_hash}

    @property
    def ca_cert(self):
        """Returns the API servers CA.

        Returns:
            The CA encoded as base64.
        """
        return read_cert(self.api.api_client.configuration.ssl_ca_cert)

    @property
    def discovery_hash(self):
        """Calculate and return a discovery_hash.

        Based on the cluster CA.

        Returns:
            A discovery hash encoded in Hex.
        """
        return ssl_discovery_hash(self.ca_cert)

    @property
    def is_ready(self):
        """Check if the API server is already available.

        Returns:
            True if it's reachable.
        """
        logging.getLogger("urllib3").setLevel(logging.ERROR)
        try:
            k8sclient.apis.core_api.CoreApi().get_api_versions()
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return True
        except urllib3.exceptions.MaxRetryError:
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            return False

    def add_all_masters_to_loadbalancer(self, cluster_name, n_masters, lb_inst):
        """Adds all master nodes to the LoadBalancer listener.

        If the number of members in the master listener pool of the LoadBalancer
        is less than expected number of masters this function will add them to
        the pool as soon as they have node status "Ready".

        Args:
            cluster_name (string): the name of the cluster
            n_master (int): Number of desired master nodes.
            lb_inst (:class:`.cloud.openstack.LoadBalancer): A configured
                LoadBalancer instance.
        """
        cond = {'Ready': 'True'}
        master_listener = lb_inst.master_listener
        listener_name = '-'.join((MASTER_LISTENER_NAME,
                                  cluster_name))
        if not master_listener:
            LOGGER.error(f"No {listener_name} found, aborting")
            sys.exit(1)

        try:
            listener_name = master_listener['name']
            mem = master_listener['pool']['members']  # noqa #  pylint: disable=unused-variable
            pool_id = master_listener['pool']['id']
        except KeyError as exc:
            LOGGER.error(f"Unable to extract info of {listener_name}: {exc}")
            sys.exit(1)

        while len(lb_inst.master_listener['pool']['members']) < n_masters:
            for item in self.api.list_node(pretty=True).items:
                if cond in [{c.type: c.status} for c in item.status.conditions]:
                    if 'master' in item.metadata.name:
                        addr_to_add = item.status.addresses[0].address
                        addr_present = [x['address'] for x in
                                        lb_inst.master_listener['pool']['members']]
                        if addr_to_add not in addr_present:
                            LOGGER.debug("Adding %s to pool '%s' (%s) ...", addr_to_add,
                                         listener_name, pool_id)
                            lb_inst.add_member(pool_id,
                                               addr_to_add)

    def run_add_script(self, pod, master_name, master_ip,
                       new_master_name, new_master_ip):
        """Executes a script inside the master-adder operator.

        This function simply takes the required arguments for the
        ``add-master-script`` shell function
        from the bootstrap script and runs it inside the master-adder
        operator pod.

        Args:
            master_name (str): an existing master host where and etcd member is
            master_ip (str): the IP address of an existing etcd member
            new_master_name (str): the host name to provision
            new_master_ip (str): the IP address of the master to provision
        """
        LOGGER.info("Retrieving etcd cluster state ...")
        etcd_cluster = self.etcd_cluster_status(pod, master_ip)
        LOGGER.debug(f"etcd cluster: {etcd_cluster}")
        cmd = ('kubectl exec -it %s -n kube-system -- /bin/bash -c '
               '"/usr/local/bin/add-master-script '
               '%s %s %s %s %s"' % (pod, new_master_name, new_master_ip,
                                    etcd_cluster, master_name, master_ip))

        LOGGER.info("Bootstrapping new master node ...")
        cmd = ('kubectl exec -it %s -n kube-system -- /bin/bash -c '
               '"/usr/local/bin/add-master-script '
               '%s %s %s %s %s"' % (pod, new_master_name, new_master_ip,
                                    etcd_cluster, master_name, master_ip))
        kctl = sp.Popen(cmd,
                        stdout=sp.PIPE,
                        stderr=sp.PIPE,
                        shell=True,
                        universal_newlines=True)

        out, err = kctl.communicate()
        LOGGER.debug(f"STDOUT: {out}")
        LOGGER.debug(f"STDERR: {err}")

        if kctl.returncode:
            raise ValueError("unable to execute adder script in adder pod")

    def get_random_master(self):
        """Returns a name and IP of a random master server in the cluster.

        Returns:
            Tuple of name and IP of a master.
        """

        nodes = self.api.list_node(pretty=True)
        nodes = [node for node in nodes.items if
                 'node-role.kubernetes.io/master' in node.metadata.labels]

        addresses = nodes[0].status.addresses

        # master_ip and master_name are the hostname and IP of an existing
        # master, where an etcd instance is already running.
        master_ip = _get_node_addr(addresses, "InternalIP")
        master_name = _get_node_addr(addresses, "Hostname")

        return master_name, master_ip

    def bootstrap_master(self, new_master_name, new_master_ip, k8s_version):
        """Run the steps required to bootstrap a new master.

        These are:
            1. Find all existing masters
            2. Get the hostname and the IP address of one
            3. Get the current etcd cluster status.
            4. Runs the add-master-script.

        Steps 3 and 4 are done in run_add_script.

        Args:
            new_master_name (str): Name of the new master
            new_master_ip (str): IP of the new master.
        """
        master_name, master_ip = self.get_random_master()

        podname = self.launch_master_adder(k8s_version)
        LOGGER.info("Preparing bootstrap of new master node...")
        self.run_add_script(podname, master_name, master_ip, new_master_name,
                            new_master_ip)
        LOGGER.success("Bootstrap of new master finished successfully")

    # pylint: disable=line-too-long
    def launch_master_adder(self, k8s_version=KUBERNETES_BASE_VERSION):
        """Launch the add_master_deployment.

        Args:
            new_master_name (str): the new master's name
            new_master_ip (str): the new master's IP address

        Return:
            str: the pod name
        """
        # if self.api.list_namespaced_config_map("kube-system", # noqa
        #   field_selector="metadata.name=dex-config"): # noqa
        # pass

        kctl = sp.Popen("kubectl apply -f -", stdin=sp.PIPE, shell=True)

        try:
            env = MASTER_ADDER_DEPLOYMENT['spec']['template']['spec']['containers'][0]['env'] # noqa
            idx = [idx for idx, val in enumerate(env) if val['name'] == 'KUBE_VERSION'][0]
            MASTER_ADDER_DEPLOYMENT['spec']['template']['spec']['containers'][0]['env'][idx]['value'] = k8s_version # noqa
        except (KeyError, IndexError) as exc:
            LOGGER.debug(exc)
            LOGGER.debug("Deployment manifest: %s", MASTER_ADDER_DEPLOYMENT)
            raise ValueError("unable to set Kubernetes version")
        kctl.communicate(json.dumps(MASTER_ADDER_DEPLOYMENT).encode())

        if kctl.returncode:
            raise ValueError("Could not apply master adder pod!")

        LOGGER.info("Waiting for pod to run ...")
        result = self.api.list_namespaced_pod(
            "kube-system",
            label_selector='k8s-app=master-adder')

        while not result.items or result.items[0].status.phase != "Running":
            time.sleep(1)
            result = self.api.list_namespaced_pod(
                "kube-system",
                label_selector='k8s-app=master-adder')
        return result.items[0].metadata.name

    def validate_context(self, conn):
        """Validate that server that we are talking to via K8S API
        is also the cloud context we are using.

        This retrieves the project ID of the Kubernetes LoadBalancer,
        then checks if it finds the same ID in any LoadBalancer of the
        currently sourced OpenStack project.

        In case the IP is not a Floating IP but only a Virtual IP, both
        IPs are simply compared.

        Args:
            conn (obj): OpenStack connection object.

        Return:
            bool
        """
        raw_ip = self.host.strip("https://").split(":")[0]
        lb_ip = conn.network.find_ip(raw_ip)

        if lb_ip:
            # We have a Floating IP
            for item in conn.load_balancer.load_balancers():
                if item.project_id == lb_ip.project_id:
                    return True
        else:
            # We have a Virtual IP
            for item in conn.load_balancer.load_balancers():
                if item.vip_address == raw_ip:
                    return True

        return False

    @retry(ValueError)
    def etcd_cluster_status(self, podname, master_ip):
        """Checks the current etcd cluster state.

        This function calls etcdctl inside a pod in order to obtain the
        current state of the etcd cluster before a new member can be added
        to it.

        Right now, etcdctl offers no convenient way to format the output so
        the URLs from the masters can be extracted, which is why jq is used here.

        Args:
            podname (str): The name of the pod where the etcdctl command
                should be sent from. Needs to be inside the kube-system namespace.
            master_ip (str)

        Returns:
            The status of the etcd as a string
            (e.g.master-1=192.168.1.102,master-2=192.168.1.103)
        """
        exec_command = [
            '/bin/sh', '-c',
            ("ETCDCTL_API=3 etcdctl --endpoints=https://%s:2379 member list"
             " -w json") % master_ip]  # noqa

        response = stream(self.api.connect_get_namespaced_pod_exec,
                          podname, 'kube-system',
                          command=exec_command,
                          stderr=True, stdin=False,
                          stdout=True, tty=False)

        if not response or not re.search("master-\\d+", response):
            LOGGER.info(response)
            raise ValueError("Could not extract current etcd cluster state!")
        # respone should be something like
        # {'members': [{'ID': 9007573287841766007, 'name': 'master-7-am',
        #  'peerURLs': ['https://10.32.192.11:2380'],
        #  'clientURLs': ['https://10.32.192.11:2379']}]}
        response = yaml.load(response)
        etcd_cluster = ",".join(("=".join((m['name'], m['peerURLs'][0])) for m
                                 in response['members']))
        LOGGER.debug("Current etcd cluster state is: %s", etcd_cluster)

        return etcd_cluster

    @retry(ValueError)
    def etcd_members(self, podname, master_ip):
        """Retrieves a dictionary with information about the etcd cluster.

        This function uses ``etcdctl member list`` to retrieve information
        about the etcd cluster, then parses that response into a dictionary
        where the keys are the names of the members and the corresponding values
        hold the rest of the information such as ID, clientURLs and peerURLs.

        Returns:
            A dictionary with information about the etcd cluster.

        Raises:
            ValueError if master_ip is not valid.
        """
        if not valid_ipv4(master_ip):
            raise ValueError(f"Invalid IP: {master_ip}")

        exec_command = [
            '/bin/sh', '-c',
            ("ETCDCTL_API=3 etcdctl --endpoints=https://%s:2379 member list"
             " -w json") % master_ip]  # noqa

        response = stream(self.api.connect_get_namespaced_pod_exec,
                          podname, 'kube-system',
                          command=exec_command,
                          stderr=True, stdin=False,
                          stdout=True, tty=False)

        return parse_etcd_response(response)

    @retry(ValueError)
    def remove_from_etcd(self, name, ignore_not_found=True):
        """Removes a member from etcd.

        The 'master-adder' operator will be used to perform the
        queries against etcd. The pod will be created if not found.

        Args:
            name (str): The name of the member to remove.
            ignore_not_found (bool): If set to False, will raise a
                ValueError if member is not part of etcd cluster.
        """

        podname = self.launch_master_adder()
        _, master_ip = self.get_random_master()

        etcd_members = self.etcd_members(podname, master_ip)
        LOGGER.debug(etcd_members)

        try:
            etcd_id = etcd_members[name]['ID']
        except KeyError:
            msg = f"'{name}' not part of etcd cluster"
            if ignore_not_found:
                LOGGER.info("Skipping removing %s from etcd: %s", name, msg)
                return

            raise ValueError(msg)

        cmd = " ".join(["ETCDCTL_API=3", "etcdctl",
                        f"--endpoints=https://{master_ip}:2379",
                        "member", "remove", f"{etcd_id}", "-w", "json"])
        exec_command = ['/bin/sh', '-c', cmd]

        response = stream(self.api.connect_get_namespaced_pod_exec,
                          podname, 'kube-system',
                          command=exec_command,
                          stderr=True, stdin=False,
                          stdout=True, tty=False)

        LOGGER.debug("%s", response)
        LOGGER.debug("Removed '%s' from etcd", name)

    def node_status(self, nodename):
        """Returns the status of a Node.

        Args:
            nodename (str): The name of the node to check.

        Returns:
            The status of the node as string or None if an error was
                encountered.
        """

        resp = None
        try:
            resp = self.api.read_node_status(
                nodename,
                pretty=True)
            LOGGER.debug("API Response: %s", resp)
        except ApiException as exc:
            LOGGER.debug("API exception: %s", exc)
            return None

        # Grab dat string
        status = [x for x in resp.status.conditions if x.type == 'Ready']

        return status[0].status

    def drain_node(self, nodename, ignore_not_found=True):
        """Drains a node of pods.

        We're using ``kubectl drain`` instead of the eviction API, since it's
        quicker and we don't have to get all the Pods of the Node first.

        Will check if the node exists first.

        Args:
            nodename (str): Name of the node to drain
            ignore_not_found (bool): If set to False, will raise
                a ValueError if the node doesn't exist.

        Raises:
            RuntimeError if ``kubectl drain`` fails.
        """

        if self.node_status(nodename) is None:
            msg = f"Node {nodename} doesn't exist"
            if ignore_not_found:
                LOGGER.info("Skipping node eviction, %s", msg)
                return

            raise ValueError(msg)

        # kubectl drain needs to block
        cmd = ["kubectl", "drain", nodename, "--ignore-daemonsets"]
        try:
            proc = sp.run(cmd,
                          check=True,
                          encoding="utf-8",
                          stdout=sp.PIPE,
                          stderr=sp.PIPE)

        except sp.CalledProcessError as exc:
            raise RuntimeError("error calling '%s':"
                               "%s" % " ".join(cmd), exc)

        LOGGER.debug("STDOUT: %s (Exit code %s)", proc.stdout,
                     proc.returncode)

    # pylint: disable=too-many-function-args
    def delete_node(self, nodename, grace_period=0, ignore_not_found=True):
        """Delete a node in Kubernetes.

        Args:
            nodename (str): The name of the node to delete.
            grace_period (int): Duration in seconds before the node should be
                delete. Defaults to 0, which means immediately.
            ignore_not_found (bool): If set to False, will raise a ValueError if
                node doesn't exist.

        Raises:
            :class:`kubernetes.client.rest.ApiException` in case the API call
                fails.
        """

        if self.node_status(nodename) is None:
            msg = f"Node {nodename} doesn't exist"
            if ignore_not_found:
                LOGGER.info("Skipping node eviction, %s", msg)
                return

            raise ValueError(msg)

        resp = self.api.delete_node(nodename, grace_period_seconds=grace_period,
                                    pretty=True)

        LOGGER.debug(resp)
        LOGGER.success("Kubernetes node '%s' has been deleted successfully",
                       nodename)

    def apply_addons(self, koris_config, apply_func=create_from_yaml):
        """apply all addons to the cluster

        Args:
            koris_config (dict): koris configuration loaded as dict
        """

        for addon in get_addons(koris_config):
            LOGGER.info("Applying add-on [%s]", addon.name)
            addon.apply(self.client, apply_func=apply_func)

    @property
    def nginx_ingress_ports(self):
        """
        get the ingress-nginx service ports as dictionary
        """
        ingress = self.api.list_namespaced_service(
            'ingress-nginx',
            label_selector="app.kubernetes.io/name=ingress-nginx",
            limit=1)

        return {i.name.upper(): i for i in ingress.items[0].spec.ports}


def add_ingress_listeners(nginx_ingress_ports, lbinst, all_ips):
    """
    Reconfigure the Openstack LoadBalancer - add an HTTP and HTTPS listener
    for nginx ingress controller

    Args:
        lbinst (:class:`.cloud.openstack.LoadBalancer`): A configured
            LoadBalancer instance.
        all_ips (list) : a list of all cluster member IPs
    """
    for key, port in {'Ingress-HTTP': 80, 'Ingress-HTTPS': 443}.items():
        protocol = key.split("-")[-1]
        name = '-'.join((key, lbinst.config['cluster-name']))
        listener = lbinst.add_listener(
            name=name,
            protocol=protocol,
            protocol_port=port)

        pool = lbinst.add_pool(listener.id, protocol=protocol, name=name)
        for ip in all_ips:
            lbinst.add_member(pool.id, ip,
                              protocol_port=nginx_ingress_ports[protocol].node_port)  # noqa


def get_addons(config):
    """
    A prototype for loading addons. There are optional addons, and non-optional
    addons.
    Currently, non-optional addons include only the metrics-server.

    Args:
        config (dict): parse yaml with an optional section, list of addons
    """

    for item in config.get('addons', {}):
        yield KorisAddon(item)

    for item in ['metrics-server', 'nginx-ingress']:
        yield KorisAddon(item)


class KorisAddon:  # pylint: disable=too-few-public-methods
    """
    Naive Addon class. Applies a kubernetes collection of resources from yml.

    Args:
        name (str): the name of the plugin
        manifest_path (str): the path where kubernetes resources are saved.

    """

    def __init__(self, name, manifest_path=MANIFESTSPATH):
        self.name = name
        self.file = os.path.join(manifest_path, name + ".yml")

    def apply(self, k8s_client, apply_func=create_from_yaml):
        """
        Apply a plugin to the cluster.
        Currently we use the Python client to apply a plugin. This might be
        limited, so we keep the possibilty to use a kubectl shell wrapper by
        making this an optional argument.

        Args:
            k8s_client:  A Kubernet API client
            apply_func: A callable that can apply a plugin to the cluster
        """
        apply_func(k8s_client, self.file, verbose=False)
