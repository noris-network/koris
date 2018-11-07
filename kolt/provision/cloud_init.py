"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import os
import textwrap


from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from kolt.util.util import get_logger

logger = get_logger(__name__)


BOOTSTRAP_SCRIPTS_DIR = "/kolt/provision/userdata/"


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
            self.combined_message.attach(sub_message)
            fh.close()

        return self.combined_message.as_string()

    def _get_cloud_provider(self):
        return self.format_file('cloud_config',
                                '/etc/kubernetes/cloud.conf',
                                self.cloud_provider,
                                encoder=lambda x: bytes(x))


class MasterInit(BaseInit):

    def __init__(self, etcds,
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
        self.role = 'master'
        self.etcds = etcds
        if cert_bundle:
            self.ca_cert_bundle = cert_bundle[0]
            self.etcd_cert_bundle = cert_bundle[1]
            self.svc_accnt_cert_bundle = cert_bundle[2]
        self.os_type = os_type
        self.os_version = os_version
        self.encryption_key = encryption_key
        self.cloud_provider = cloud_provider
        self.token_csv_data = token_csv_data

    def get_files_config(self):
        return ""


class NodeInit(BaseInit):

    def __init__(self, token,
                 ca_cert_bundle,
                 etcd_cert_bundle,
                 svc_account_bundle,
                 etcd_cluster_info, calico_token,
                 lb_ip,
                 cloud_provider=None,
                 os_type='ubuntu', os_version="16.04"):

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

    def get_files_config(self):
        """
        write the section write_files into the cloud-config
        """
        return ""
