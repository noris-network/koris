"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import datetime
import json
import logging
import os
import textwrap
import subprocess as sp
import sys

import yaml

from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from kolt.ssl import create_key, create_certificate, b64_key, b64_cert

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)


class CloudInit:

    def __init__(self, role, hostname, cluster_info, os_type='ubuntu',
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
        self.os_type = os_type
        self.os_version = os_version

    def _etcd_cluster_info(self):
        """
        Write the etcd cluster info to /etc/kubernetes/etcd_cluster
        """

        cluster_info_part = """
        #cloud-config
        write_files:
          - content: |
              NODE01={n01_name}
              NODE02={n02_name}
              NODE03={n03_name}
              NODE01_IP={n01_ip}
              NODE02_IP={n02_ip}
              NODE03_IP={n03_ip}
              INITIAL_CLUSTER={n01_name}=https://{n01_ip}:2380,{n02_name}=https://{n02_ip}:2380,{n03_name}=https://{n03_ip}:2380

            owner: root:root
            permissions: '0644'
            path: /etc/kubernetes/etcd_cluster
        """.format(**self.cluster_info)
        return textwrap.dedent(cluster_info_part)

    def _get_ca_and_certs(self):
        ca_key = create_key()
        ca_cert = create_certificate(ca_key, ca_key.public_key(),
                                     "DE", "BY", "NUE",
                                     "noris-network", "CA", ["CA"])

        hostnames = [v for k, v in self.cluster_info.items() if v.endswith("_name")]

        k8s_key = create_key()
        k8s_cert = create_certificate(ca_key, k8s_key.public_key(),
                                     "DE", "BY", "NUE", "noris-network",
                                     "Kubernetes", hostnames)
        self.ca_key, self.ca_cert = ca_key, ca_cert
        self.k8s_key, self.k8s_cert =  k8s_key, k8s_cert

        return ca_key, ca_cert, k8s_key, k8s_cert

    def _get_certificate_info(self):
        """
        write certificates to destination directory
        """
        ca_key, ca_cert, k8s_key, k8s_cert = self._get_ca_and_certs()

        b64_k8s_key = b64_key(k8s_key)
        b64_ca_cert = b64_cert(ca_cert)
        b64_k8s_cert = b64_cert(k8s_cert)

        certificate_info = """
        #cloud-config
        write_files:
         - path: /etc/ssl/ca.pem
           encoding: b64
           content: {CA_CERT}
           owner: root:root
           permissions: '0600'
         - path: /etc/ssl/kubernetes.pem
            encoding: b64
           content: {KUBERNETES_CERT}
           owner: root:root
           permissions: '0600'
         - path: /etc/ssl/kubernetes-key.pem
           encoding: b64
           content: {K8S_KEY}
           owner: root:root
           permissions: '0600'
        """.format(
            CA_CERT=b64_ca_cert, K8S_KEY=b64_k8s_key, KUBERNETES_CERT=b64_k8s_cert
            )
        return textwrap.dedent(certificate_info)

    def __str__(self):

        if self.cluster_info:
            sub_message = MIMEText(
                self._etcd_cluster_info(),
                _subtype='text/cloud-config')
            sub_message.add_header('Content-Disposition', 'attachment',
                                   filename="/etc/kubernetes/etc_cluster")
            self.combined_message.attach(sub_message)

            sub_message = MIMEText(self._get_certificate_info(),
                                   _subtype='text/cloud-config')
            sub_message.add_header('Content-Disposition', 'attachment',
                                   filename="/etc/cert.conf")
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
