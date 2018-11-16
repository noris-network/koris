"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import json
import os
import re
import textwrap


from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pkg_resources import (Requirement, resource_filename)

from koris.ssl import (b64_key, b64_cert)
from koris.util.util import (encryption_config_tmpl,
                             calicoconfig, get_kubeconfig_yaml,
                             get_logger)

LOGGER = get_logger(__name__)


BOOTSTRAP_SCRIPTS_DIR = "/koris/provision/userdata/"


class BaseInit:
    """
    Base class for cloud inits
    """

    @staticmethod
    def format_file(
            part_name, path_name, content,
            encoder=lambda x: base64.b64encode(x),  # pylint: disable=unnecessary-lambda
            owner='root',
            group='root',
            permissions='0600'):
        """
        format a file to the correct section in cloud init
        """
        part = """
        # {part_name}
         - path: {path_name}
           encoding: b64
           content: {content}
           owner: {owner}:{group}
           permissions: '{permissions}'
        """
        part = textwrap.dedent(part)

        return part.format(part_name=part_name,
                           path_name=path_name,
                           content=encoder(content).decode(),
                           owner=owner,
                           group=group,
                           permissions=permissions).lstrip()

    def __str__(self):

        sub_message = MIMEText(self.get_files_config(),
                               _subtype='text/cloud-config')
        sub_message.add_header('Content-Disposition', 'attachment')
        self.combined_message.attach(sub_message)  # pylint: disable=no-member

        k8s_bootstrap = "bootstrap-k8s-%s-%s-%s.sh" % (
            self.role, self.os_type, self.os_version)  # pylint: disable=no-member

        # process bootstrap script and generic cloud-init file
        for item in ['generic', k8s_bootstrap]:
            fh = open(resource_filename(Requirement('koris'),
                                        os.path.join(BOOTSTRAP_SCRIPTS_DIR,
                                                     item)))
            # we currently blindly assume the first line is a mimetype
            # or a shebang
            main_type, _subtype = fh.readline().strip().split("/", 1)

            if '#!' in main_type:
                _subtype = 'x-shellscript'
            #    fh.seek(0)

            sub_message = MIMEText(fh.read(), _subtype=_subtype)
            sub_message.add_header('Content-Disposition',
                                   'attachment', filename="%s" % item)
            self.combined_message.attach(sub_message)  # pylint: disable=no-member
            fh.close()

        return self.combined_message.as_string()  # pylint: disable=no-member

    def _get_cloud_provider(self):
        return self.format_file(
            'cloud_config',
            '/etc/kubernetes/cloud.conf',
            self.cloud_provider,  # pylint: disable=no-member
            encoder=lambda x: bytes(x))  # pylint: disable=unnecessary-lambda

    def get_files_config(self):
        """
        join all parts of the cloud-init
        """
        raise NotImplementedError


class MasterInit(BaseInit):
    """
    Create a cloud  init config for a master node
    """

    def __init__(self, hostname, etcds,
                 certs, encryption_key=None,
                 cloud_provider=None,
                 token_csv_data="",
                 os_type='ubuntu',
                 os_version="16.04"):
        """
        cluster_info - a dictionary with infromation about the etcd cluster
        members
        """
        self.combined_message = MIMEMultipart()
        self.hostname = hostname
        self.role = 'master'
        self.etcds = etcds
        self.certs = certs
        self.os_type = os_type
        self.os_version = os_version
        self.encryption_key = encryption_key
        self.cloud_provider = cloud_provider
        self.token_csv_data = token_csv_data

    def _etcd_cluster_info(self, port=2380):
        """
        Write the etcd cluster info to /etc/systemd/system/etcd.env
        """
        tmpl = "%s=https://%s:%d"
        cluster_info_part = """

        # systemd env
         - path: /etc/systemd/system/etcd.env
           owner: root:root
           permissions: '0644'
           content: |
             NODE01_IP={}
             NODE02_IP={}
             NODE03_IP={}
             INITIAL_CLUSTER={}
        """.format(self.etcds[0].ip_address,
                   self.etcds[1].ip_address,
                   self.etcds[2].ip_address,
                   ",".join(
                       tmpl % (etcd.name.lower(), etcd.ip_address, port) for
                            etcd in self.etcds))
        return textwrap.dedent(cluster_info_part)

    def _get_token_csv(self):
        """
        write access data to /var/lib/kubernetes/token.csv
        """

        return self.format_file('token_csv', '/var/lib/kubernetes/token.csv',
                                self.token_csv_data,
                                encoder=lambda x: x.encode())

    def _get_certificate_info(self):
        # write data for CA for the etcds
        etcd_ca = self.format_file("etcd_ca",
                                   "/etc/kubernetes/pki/etcd/ca.crt",
                                   self.certs['etcd_ca'].cert,
                                   encoder=lambda x: b64_cert(x).encode())

        etcd_ca_key = self.format_file("etcd_ca_key",
                                       "/etc/kubernetes/pki/etcd/ca.key",
                                       self.certs['etcd_ca'].key,
                                       encoder=lambda x: b64_key(x).encode())

        # write data for this host as etcd peer, this certificate is used
        # for opening up connections to peers and for validating incoming
        # connections from peers
        etcd_peer = self.format_file('peer',
                                     "/etc/kubernetes/pki/etcd/peer.crt",
                                     self.certs["%s-peer" % self.hostname].cert,  # noqa
                                     encoder=lambda x: b64_cert(x).encode())

        etcd_peer_key = self.format_file('peer_key',
                                         "/etc/kubernetes/pki/etcd/peer.key",
                                         self.certs["%s-peer" % self.hostname].key,  # noqa
                                         encoder=lambda x: b64_key(x).encode())

        # write data for this host as etcd server, this certificate is used
        # for validating incoming client connections (from K8s)
        etcd_server = self.format_file('server',
                                     "/etc/kubernetes/pki/etcd/server.crt",
                                     self.certs["%s-server" % self.hostname].cert,  # noqa
                                     encoder=lambda x: b64_cert(x).encode())

        etcd_server_key = self.format_file('server_key',
                                         "/etc/kubernetes/pki/etcd/server.key",
                                         self.certs["%s-server" % self.hostname].key,  # noqa
                                         encoder=lambda x: b64_key(x).encode())

        # write out certificate data so that the api-server running on this
        # host is able to access the etcd cluster
        api_etcd_client = self.format_file('apiserver-etcd-client',
                                     "/etc/kubernetes/pki/etcd/api-ectd-client.crt", # noqa
                                     self.certs["apiserver-etcd-client"].cert,  # noqa
                                     encoder=lambda x: b64_cert(x).encode())

        api_etcd_client_key = self.format_file('apiserver-etcd-client_key',
                                     "/etc/kubernetes/pki/etcd/api-ectd-client.key", # noqa
                                     self.certs["apiserver-etcd-client"].key,  # noqa
                                     encoder=lambda x: b64_key(x).encode())

        # write certificates needed for K8s
        # this CA will be used to authenticate accesses to the K8S api-server.
        # It is _not_ the same as the CA for etcd!
        ca = self.format_file("ca",
                              "/etc/ssl/kubernetes/ca.pem",
                              self.certs['ca'].cert,
                              encoder=lambda x: b64_cert(x).encode())

        ca_key = self.format_file("ca-key",
                                  "/etc/ssl/kubernetes/ca-key.pem",
                                  self.certs['ca'].key,
                                  encoder=lambda x: b64_key(x).encode())

        # this certifcate is used for communications within K8s
        k8s_key = self.format_file("k8s-key",
                                   "/etc/ssl/kubernetes/kubernetes-key.pem",
                                   self.certs['k8s'].key,
                                   encoder=lambda x: b64_key(x).encode())
        k8s_cert = self.format_file("k8s-cert",
                                    "/etc/ssl/kubernetes/kubernetes.pem",
                                    self.certs['k8s'].cert,
                                    encoder=lambda x: b64_cert(x).encode())

        return "".join((etcd_ca, etcd_ca_key, etcd_peer, etcd_peer_key,
                        etcd_server, etcd_server_key, api_etcd_client,
                        api_etcd_client_key, ca, ca_key, k8s_key,
                        k8s_cert, ))

    def _get_encryption_config(self):
        encryption_config = re.sub("%%ENCRYPTION_KEY%%",
                                   self.encryption_key,
                                   encryption_config_tmpl).encode()

        return self.format_file(
            "encryption_config",
            "/var/lib/kubernetes/encryption-config.yaml",
            encryption_config)

    def _get_svc_account_info(self):

        svc_accnt_key = self.format_file(
            "svc-account-key",
            "/etc/ssl/kubernetes/service-accounts-key.pem",
            self.certs['service-account'].key,
            encoder=lambda x: b64_key(x).encode())

        svc_accnt_cert = self.format_file(
            "svc-account-cert",
            "/etc/ssl/kubernetes/service-accounts.pem",
            self.certs['service-account'].cert,
            encoder=lambda x: b64_cert(x).encode())

        return svc_accnt_key + svc_accnt_cert

    def get_files_config(self):
        """
        write the section write_files into the cloud-config
        """
        config = textwrap.dedent("""
        #cloud-config
        write_files:
        """) + self._get_certificate_info().lstrip() \
             + self._etcd_cluster_info().lstrip() \
             + self._get_svc_account_info().lstrip() \
             + self._get_encryption_config().lstrip() \
             + self._get_cloud_provider().lstrip() \
             + self._get_token_csv().lstrip()

        return config


class NodeInit(BaseInit):

    def __init__(self, instance, token,
                 ca_cert_bundle,
                 etcd_cert_bundle,
                 svc_account_bundle,
                 etcd_cluster_info, calico_token,
                 lb_ip,
                 cloud_provider=None,
                 os_type='ubuntu', os_version="16.04"):

        self.instance = instance
        self.role = 'node'
        self.token = token
        self.ca_cert_bundle = ca_cert_bundle
        self.os_type = os_type
        self.os_version = os_version
        self.etcd_cluster_info = etcd_cluster_info
        self.calico_token = calico_token
        self.lb_ip_address = lb_ip
        self.combined_message = MIMEMultipart()
        self.cloud_provider = cloud_provider
        self.etcd_cert_bundle = etcd_cert_bundle
        self.svc_accnt_bundle = svc_account_bundle

    def _get_certificate_info(self):
        """
        write certificates to destination directory
        """
        ca = self.format_file("ca",
                              "/etc/ssl/kubernetes/ca.pem",
                              self.ca_cert_bundle.cert,
                              encoder=lambda x: b64_cert(x).encode())

        k8s_key = self.format_file("k8s-key",
                                   "/etc/ssl/kubernetes/kubernetes-key.pem",
                                   self.etcd_cert_bundle.key,
                                   encoder=lambda x: b64_key(x).encode())
        k8s_cert = self.format_file("k8s-cert",
                                    "/etc/ssl/kubernetes/kubernetes.pem",
                                    self.etcd_cert_bundle.cert,
                                    encoder=lambda x: b64_cert(x).encode())

        return ca + k8s_key + k8s_cert

    def _get_svc_account_info(self):

        svc_accnt_key = self.format_file(
            "svc-account-key",
            "/etc/ssl/kubernetes/service-accounts-key.pem",
            self.svc_accnt_bundle.key,
            encoder=lambda x: b64_key(x).encode())

        svc_accnt_cert = self.format_file(
            "svc-account-cert",
            "/etc/ssl/kubernetes/service-accounts.pem",
            self.svc_accnt_bundle.cert,
            encoder=lambda x: b64_cert(x).encode())

        return svc_accnt_key + svc_accnt_cert

    def _get_kubelet_config(self):

        kubeconfig = get_kubeconfig_yaml(
            "https://%s:6443" % self.lb_ip_address,
            "kubelet",
            self.token,
            skip_tls=True
        )

        kubelet_config_part = """
        # encryption_config
         - path: /var/lib/kubelet/kubeconfig.yaml
           encoding: b64
           content: {}
           owner: root:root
           permissions: '0600'
        """.format(kubeconfig)

        return textwrap.dedent(kubelet_config_part).lstrip()

    def _get_kubeproxy_info(self):
        kubeproxy_part = """
        # kube proxy configuration
         - path: /etc/systemd/system/kube-proxy.env
           encoding: b64
           content: {}
           owner: root:root
           permissions: '0600'
        """.format(
            base64.b64encode(("LB_IP=%s" %
                              self.lb_ip_address).encode()).decode()  # noqa
            )

        return textwrap.dedent(kubeproxy_part).lstrip()

    def _get_calico_config(self, port=2739):
        calicoconfig['etcd_endpoints'] = ",".join(
            "https://%s:%d" % (etcd_host.ip_address, port)
            for etcd_host in self.etcd_cluster_info)

        cc = json.dumps(calicoconfig, indent=2).encode()

        return self.format_file(
            'calico_config',
            '/etc/cni/net.d/10-calico.conf',
            cc,
            encoder=lambda x: base64.b64encode(x))  # pylint: disable=unnecessary-lambda

    def _get_kubelet_env_info(self):
        """
        Write the kubelet environment info to /etc/systemd/system/kubelet.env
        """
        kubelet_env_info_part = """

        # systemd env
         - path: /etc/systemd/system/kubelet.env
           owner: root:root
           permissions: '0644'
           content: |
             NODE_IP={}
        """.format(self.instance.ip_address)
        return textwrap.dedent(kubelet_env_info_part)

    def get_files_config(self):
        """
        write the section write_files into the cloud-config
        """
        config = textwrap.dedent("""
        #cloud-config
        write_files:
        """) + self._get_kubelet_config() \
             + self._get_certificate_info() \
             + self._get_svc_account_info() \
             + self._get_kubeproxy_info() \
             + self._get_cloud_provider().lstrip() \
             + self._get_calico_config() \
             + self._get_kubelet_env_info()

        return config
