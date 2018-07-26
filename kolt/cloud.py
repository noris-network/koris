"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import json
import logging
import os
import re
import textwrap


from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from kolt.ssl import (b64_key, b64_cert)
from kolt.util import (encryption_config_tmpl,
                       calicoconfig, get_kubeconfig_yaml)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)


class BaseInit:

    def format_file(self, part_name, path_name, content,
                    encoder=lambda x: base64.b64encode(x),
                    owner='root',
                    group='root',
                    permissions='0600'):
        """

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
        self.combined_message.attach(sub_message)

        k8s_bootstrap = "bootstrap-k8s-%s-%s-%s.sh" % (self.role,
                                                       self.os_type,
                                                       self.os_version)

        # process bootstrap script and generic cloud-init file
        for item in ['generic', k8s_bootstrap]:
            fh = open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt',
                                                     'cloud-inits',
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
            self.combined_message.attach(sub_message)
            fh.close()

        return self.combined_message.as_string()


class MasterInit(BaseInit):

    def __init__(self, role, cluster_info,
                 cert_bundle=None, encryption_key=None,
                 cloud_provider=None,
                 token_csv_data="",
                 os_type='ubuntu',
                 os_version="16.04"):
        """
        cluster_info - a dictionary with infromation about the etcd cluster
        members
        """
        self.combined_message = MIMEMultipart()

        if role not in ('master', 'node'):
            raise ValueError("Incorrect os_role!")
        self.role = role
        self.cluster_info = cluster_info
        if cert_bundle:
            self.ca_cert_bundle = cert_bundle[0]
            self.etcd_cert_bundle = cert_bundle[1]
            self.svc_accnt_cert_bundle = cert_bundle[2]
        self.os_type = os_type
        self.os_version = os_version
        self.encryption_key = encryption_key
        self.cloud_provider = cloud_provider
        self.token_csv_data = token_csv_data

    def _etcd_cluster_info(self):
        """
        Write the etcd cluster info to /etc/systemd/system/etcd.env
        """

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
        """.format(self.cluster_info[0].ip_address,
                   self.cluster_info[1].ip_address,
                   self.cluster_info[2].ip_address,
                   ",".join(str(etcd_host) for etcd_host in self.cluster_info))
        return textwrap.dedent(cluster_info_part)

    def _get_token_csv(self):
        """
        write access data to /var/lib/kubernetes/token.csv
        """

        return self.format_file('token_csv', '/var/lib/kubernetes/token.csv',
                                self.token_csv_data,
                                encoder=lambda x: x.encode())

    def _get_certificate_info(self):

        ca = self.format_file("ca",
                              "/etc/ssl/kubernetes/ca.pem",
                              self.ca_cert_bundle.cert,
                              encoder=lambda x: b64_cert(x).encode())

        ca_key = self.format_file("ca-key",
                                  "/etc/ssl/kubernetes/ca-key.pem",
                                  self.ca_cert_bundle.key,
                                  encoder=lambda x: b64_key(x).encode())

        k8s_key = self.format_file("k8s-key",
                                   "/etc/ssl/kubernetes/kubernetes-key.pem",
                                   self.etcd_cert_bundle.key,
                                   encoder=lambda x: b64_key(x).encode())
        k8s_cert = self.format_file("k8s-cert",
                                    "/etc/ssl/kubernetes/kubernetes.pem",
                                    self.etcd_cert_bundle.cert,
                                    encoder=lambda x: b64_cert(x).encode())
        return ca + ca_key + k8s_key + k8s_cert

    def _get_encryption_config(self):
        encryption_config = re.sub("%%ENCRYPTION_KEY%%",
                                   self.encryption_key,
                                   encryption_config_tmpl).encode()

        return self.format_file(
            "encryption_config",
            "/var/lib/kubernetes/encryption-config.yaml",
            encryption_config)

    def _get_cloud_provider(self):

        return self.format_file('cloud_config',
                                '/etc/kubernetes/cloud.conf',
                                self.cloud_provider,
                                encoder=lambda x: bytes(x))

    def _get_svc_account_info(self):

        svc_accnt_key = self.format_file(
            "svc-account-key",
            "/etc/ssl/kubernetes/service-accounts-key.pem",
            self.svc_accnt_cert_bundle.key,
            encoder=lambda x: b64_key(x).encode())

        svc_accnt_cert = self.format_file(
            "svc-account-cert",
            "/etc/ssl/kubernetes/service-accounts.pem",
            self.svc_accnt_cert_bundle.cert,
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

    def __str__(self):

        if self.cluster_info:
            sub_message = MIMEText(self.get_files_config(),
                                   _subtype='text/cloud-config')
            sub_message.add_header('Content-Disposition', 'attachment')
            self.combined_message.attach(sub_message)

        k8s_bootstrap = "bootstrap-k8s-%s-%s-%s.sh" % (self.role,
                                                       self.os_type,
                                                       self.os_version)

        # process bootstrap script and generic cloud-init file
        for item in ['generic', k8s_bootstrap]:
            fh = open(resource_filename(Requirement('kolt'),
                                        os.path.join('kolt',
                                                     'cloud-inits',
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
            self.combined_message.attach(sub_message)
            fh.close()

        return self.combined_message.as_string()


class NodeInit(BaseInit):

    def __init__(self, role, token,
                 ca_cert_bundle,
                 etcd_cert_bundle,
                 svc_account_bundle,
                 etcd_cluster_info, calico_token,
                 os_type='ubuntu', os_version="16.04"):

        self.role = role
        self.token = token
        self.ca_cert_bundle = ca_cert_bundle
        self.os_type = os_type
        self.os_version = os_version
        self.etcd_cluster_info = etcd_cluster_info
        self.calico_token = calico_token
        self.combined_message = MIMEMultipart()

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

    def _get_kubeconfig(self):
        kubeconfig_part = """
        # calico kubeconfig
         - path: /etc/calico/kube/kubeconfig
           encoding: b64
           content: {}
           owner: root:root
           permissions: '0600'
        """.format(get_kubeconfig_yaml(
            "https://%s:6443" % self.etcd_cluster_info[0].name,
            "calico",
            self.calico_token,
            skip_tls=True))

        return textwrap.dedent(kubeconfig_part).lstrip()

    def _get_kubelet_config(self):

        kubeconfig = get_kubeconfig_yaml(
            "https://%s:6443" % self.etcd_cluster_info[0].name,
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

    def _get_calico_config(self):
        calicoconfig['plugins'][0]['etcd_endpoints'] = ",".join(
            "http://%s:%d" % (etcd_host.ip_address, etcd_host.port)
            for etcd_host in self.etcd_cluster_info)

        cc = json.dumps(calicoconfig, indent=2).encode()

        return self.format_file(
            'calico_config',
            '/etc/cni/net.d/10-calico.conf',
            cc,
            encoder=lambda x: base64.b64encode(x))

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
             + self._get_calico_config() \
             + self._get_kubeconfig()

        return config
