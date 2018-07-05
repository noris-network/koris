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

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography import utils


from pkg_resources import (Requirement, resource_filename)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
# add ch to logger
logger.addHandler(ch)

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

# TODO: read these values from the main config
default_csr_config = {"CN": "Kubernetes",
                      "key": {"algo": "rsa",
                              "size": 4096},
                      "names": [{"C": "US",
                                 "L": "Portland",
                                 "O": "Kubernetes",
                                 "OU": "CA",
                                 "ST": "Oregon"}
                                ]
                      }


default_ca_config = {"signing": {
                     "profiles": {"kubernetes":
                                  {"usages":
                                   ["signing",
                                    "key encipherment",
                                    "server auth",
                                    "client auth"],
                                   }
                                  }}}


def create_private_key(size=2048, public_exponent=65537):
    """
    Pure python creation of private keys

    Taken from https://cryptography.io/en/stable/x509/tutorial/

    Args:
        size (int): the byte size of the key to create
        public_exponent (int): the exponent size of the public key

    Returns:
       SSL key instance (see cryptography.io for more info)
    """
    key = rsa.generate_private_key(
        public_exponent=public_exponent,
        key_size=size,
        backend=default_backend()
    )

    return key


def create_certificate(key, country, state_province, locality, orga, name, hosts):
    """
    Pure python creation of SSL certificates

    Taken from https://cryptography.io/en/stable/x510/tutorial/
    Args:
        key (SSL key instance): the key to sign the certificate with.
        country (str): The country name
        state_province (str):
        locality (str):
        orga (str):
        name (str):

    Returns:
        x509.Certificate object instance (see cryptography.io for more info).

    """
    # Various details about who we are. For a self-signed certificate the
    # subject and issuer are always the same.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_after(
        # Our certificate will be valid for 1800 days
        datetime.datetime.utcnow() + datetime.timedelta(days=1800)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(host) for host in hosts]),
        critical=False,
        # Sign our certificate with our private key
    ).sign(key, hashes.SHA256(), default_backend())

    return cert


def write_key(key, passwd=None, filename="ca-key.pem"):
    """
    Write the key instance to the file as ASCII string

    Args:
        key (SSL key instance)
        passwd (str): if given the key will be protected with this password
        filename (str): the file to write
    """
    if passwd:
        enc_algo = serialization.BestAvailableEncryption(passwd.encode())
    else:
        enc_algo = serialization.NoEncryption()

    # Write our key to disk for safe keeping
    with open(filename, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=enc_algo,))


def write_cert(cert, filename):
    """
   Write the certifiacte instance to the file as ASCII string

   Args:
       cert (SSL certificate instance)
       filename (str): the file to write
   """

    with open(filename, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def create_ca(expiry_time, ca_name, cert_dir):
    key = create_private_key()
    ca_cert = create_certificate(key,
                                 "DE",
                                 "BY",
                                 "NUE",
                                 "noris-network",
                                 "Kubernetes",
                                 ["Kubernetes"])
    write_key(key, filename=os.path.join(cert_dir, "%s-key.pem" % ca_name))
    write_cert(ca_cert, os.path.join(cert_dir, "%s.pem" % ca_name))
    return key


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

        #sub_message = MIMEText(self._get_certificate_info(),
        #                       _subtype='text/cloud-config')
        #sub_message.add_header('Content-Disposition', 'attachment',
        #                       filename="/etc/cert.conf")
        #self.combined_message.attach(sub_message)

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
