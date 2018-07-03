"""
This modules contains some helper functions to inject cloud-init
to booted machines. At the moment only Cloud Inits for Ubunut 16.04 are
provided
"""
import base64
import json
import os
import textwrap
import subprocess as sp
import sys

from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


INCLUSION_TYPES_MAP = {
    '#include': 'text/x-include-url',
    '#include-once': 'text/x-include-once-url',
    '#!': 'text/x-shellscript',
    '#cloud-config': 'text/cloud-config',
    '#upstart-job': 'text/upstart-job',
    '#part-handler': 'text/part-handler',
    '#cloud-boothook': 'text/cloud-boothook',
    '#cloud-config-archive': 'text/cloud-config-archive',
    '#cloud-config-jsonp': 'text/cloud-config-jsonp',
}


default_ca_config = {"signing": {
                     "default": {"expiry": "8760h"},
                     "profiles": {"kubernetes":
                                  {"usages":
                                   ["signing",
                                    "key encipherment",
                                    "server auth",
                                    "client auth"],
                                   "expiry": "8760h"
                                   }
                                  }}}


def create_ca(ca_config):
    cmd = "cfssl gencert -initca -"
    proc = sp.Popen(cmd, shell=True, stdin=sp.PIPE,
                    stdout=sp.PIPE, stderr=sp.PIPE)

    out, err = proc.communicate(json.dumps(ca_config).encode())

    if proc.returncode:
        sys.exit("could not generate CA certificate.")

    # this returns a dictionary with key 'csr', 'cert', 'key'
    # they are later written as ca.csr, ca.pem, ca-key.pem
    return json.loads(out.decode())


def create_signed_cert(name, hostnames):
    """
    :param hostnames: comma separated list of hostnames for this certificate,
        e.g. 10.32.0.1,10.240.0.10,10.240.0.11,10.240.0.12,
        ${KUBERNETES_PUBLIC_ADDRESS},127.0.0.1,kubernetes.default
    :param name: name of the certificate: name.pem and name-key.pem
    """
    cfssl = os.path.join(os.path.split(os.path.realpath(__file__))[0], "cfssl")

    if (not os.path.exists("./ca.pem")) or (
            not os.path.exists("./ca-key.pem")):
        raise IOError("could not find CA certificate.")

    cmd = "cfssl gencert \
                -ca=./ca.pem \
                -ca-key=./ca-key.pem \
                -config={} \
                -hostname={} \
                -profile=kubernetes \
                {} | cfssljson -bare {}"

    cmd = cmd.format(os.path.join(cfssl, "ca-config.json"),
                     os.path.join(cfssl, hostnames),
                     os.path.join(cfssl, "cert-csr.json"),
                     "./" + name
                     )

    proc = sp.run(cmd, shell=True, stdout=sys.stdout, stderr=sys.stderr)

    if(proc.returncode != os.EX_OK):
        raise IOError("could not generate certificate.")


class CloudInit:

    def __init__(self, role, hostname, cluster_info, os_type='ubuntu',
                 os_version="16.04"):

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
        Write the etcd cluster info to /etc/kolt.conf
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

              owner: root:root
              permissions: '0644'
              path: /etc/kolt.conf
        """.format(**self.cluster_info)
        return textwrap.dedent(cluster_info_part)

    def _get_certificate_info(self):
        """
        write certificates to destination directory
        """
        certificate_info = """
        #cloud-config
        write_files:
            - path: /etc/ssl/ca.pem
              encoding: b64
              content: {CA_CERT}
              owner: root:root
              permissions: '0600'
            - path: /etc/ssl/{HOST_CERT_NAME}
              encoding: b64
              content: {HOST_CERT}
              owner: root:root
              permissions: '0600'
            - path: /etc/ssl/{HOST_KEY_NAME}
              encoding: b64
              content: {HOST_KEY}
              owner: root:root
              permissions: '0600'
        """.format(
            CA_CERT=base64.b64encode(
                open("./ca.pem", "rb").read()).decode(),
            HOST_CERT=base64.b64encode(
                open("./" + self.hostname + ".pem", "rb").read()).decode(),
            HOST_CERT_NAME=self.hostname + ".pem",
            HOST_KEY=base64.b64encode(
                open("./" + self.hostname + "-key.pem", "rb").read()).decode(),
            HOST_KEY_NAME=self.hostname + "-key.pem"
        )
        ret = textwrap.dedent(certificate_info)
        print(ret)
        return ret

    def __str__(self):

        if self.cluster_info:
            sub_message = MIMEText(
                self._etcd_cluster_info(),
                _subtype='text/cloud-config')
            sub_message.add_header('Content-Disposition', 'attachment',
                                   filename="/etc/kolt.conf")
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
