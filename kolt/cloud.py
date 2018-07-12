"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import logging
import os
import textwrap


from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from kolt.ssl import (b64_key, b64_cert)
from kolt.util import encryption_config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)


class CloudInit:

    def __init__(self, role, hostname, cluster_info,
                 cert_bundle, encryption_key,
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
        self.hostname = hostname
        self.cluster_info = cluster_info
        self.etcd_cert_bundle = cert_bundle[0]
        self.svc_accnt_cert_bundle = cert_bundle[1]
        self.os_type = os_type
        self.os_version = os_version
        self.encryption_key = encryption_key

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

    def _get_ca_and_certs(self):

        return (self.etcd_cert_bundle.ca_cert,
                self.etcd_cert_bundle.key,
                self.etcd_cert_bundle.cert)

    def _get_certificate_info(self):
        """
        write certificates to destination directory
        """
        ca_cert, k8s_key, k8s_cert = self._get_ca_and_certs()

        b64_k8s_key = b64_key(k8s_key)
        b64_ca_cert = b64_cert(ca_cert)
        b64_k8s_cert = b64_cert(k8s_cert)

        certificate_info = """
        # certificates
         - path: /etc/ssl/kubernetes/ca.pem
           encoding: b64
           content: {CA_CERT}
           owner: root:root
           permissions: '0600'
         - path: /etc/ssl/kubernetes/kubernetes.pem
           encoding: b64
           content: {KUBERNETES_CERT}
           owner: root:root
           permissions: '0600'
         - path: /etc/ssl/kubernetes/kubernetes-key.pem
           encoding: b64
           content: {K8S_KEY}
           owner: root:root
           permissions: '0600'
        """.format(
            CA_CERT=b64_ca_cert.lstrip(),
            K8S_KEY=b64_k8s_key.lstrip(),
            KUBERNETES_CERT=b64_k8s_cert.lstrip())

        return textwrap.dedent(certificate_info)

    def _get_encryption_config(self):
        encryption_config_part = """
        # encryption_config
         - path: /var/lib/Kubernetes/encryption-config.yaml
           encoding: b64
           content: {}
           owner: root:root
        """.format(
            base64.b64encode(
                encryption_config.format(self.encryption_key).encode()
            ))

        return textwrap.dedent(encryption_config_part)

    def _get_svc_account_info(self):

        svc_accnt_key = b64_key(self.svc_accnt_cert_bundle.key).lstrip()
        svc_accnt_cert = b64_cert(self.svc_accnt_cert_bundle.cert).lstrip()

        service_account_certs = """
        # service accounts
         - path: /etc/ssl/Kubernetes/service-accounts.pem
           encoding: b64
           content: {svc_accnt_cert}
           owner: root:root
           permissions: '0600'
         - path: /etc/ssl/Kubernetes/service-accounts-key.pem
           encoding: b64
           content: {svc_accnt_key}
           owner: root:root
           permissions: '0600'""".format(svc_accnt_cert=svc_accnt_cert,
                                         svc_accnt_key=svc_accnt_key)

        return textwrap.dedent(service_account_certs)

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
             + self._get_encryption_config().lstrip()

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
