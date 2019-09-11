"""
ssl.py hold all ssl certifcates creation utilities and classes
"""
# pylint: disable=too-many-locals,too-many-arguments

import base64
import datetime
import ipaddress
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes

from koris.util.logger import Logger

LOGGER = Logger(__name__)


def create_key(size=2048, public_exponent=65537):
    """Create an RSA private key

    Args:
        size (int) - the key byte size
        public_exponent (int) - the key public_exponent

    Return:
        rsa key object instance
    """
    key = rsa.generate_private_key(
        public_exponent=public_exponent,
        key_size=size,
        backend=default_backend()
    )
    return key


# pylint: disable=dangerous-default-value
def create_ca(private_key, public_key, country,
              state_province, locality, orga, unit, name,
              key_usage=[True, False, True, False, False, True,
                         False, False, False]):
    """
    create a CA signed with private_key

    Args:
        private_key (inst): private key instance to sign the CA
        public_key (inst): public key for the CSR
        country (str): the country for the CSR
        state_province (str): the state or province for the CSR
        locality (str): the locality for the CSR
        orga (str): the organization for the CSR
        unit (str): the unit for the CSR
        name (str): the name for the CSR
        key_usage (list): Key Usage parameters. Indices stand for:
            [digital_signature, content_commitment, key_encipherment,
            data_encipherment, key_agreement, key_cert_sign, crl_sign,
            encipher_only, decipher_only]

    Return:
        ssl certificate object
    """
    issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        public_key
    ).not_valid_before(
        # note to future people
        # sometimes your desktop server will have a time
        # deviation from the server, to avoid the certificate
        # invalidation we introduce a little buffer in the
        # time
        datetime.datetime.utcnow() + datetime.timedelta(minutes=-10)
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_after(
        # Our certificate will be valid for 1800 days
        datetime.datetime.utcnow() + datetime.timedelta(days=1800))

    cert = cert.add_extension(
        x509.KeyUsage(*key_usage),
        critical=True)

    cert = cert.add_extension(x509.BasicConstraints(True, None), critical=True)
    cert = cert.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(public_key),
        critical=False)

    cert = cert.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key),
        critical=False)

    cert = cert.sign(private_key, hashes.SHA256(), default_backend())

    return cert


def create_certificate(ca_bundle, public_key, country,
                       state_province, locality, orga, unit, name,
                       hosts=None, ips=None,
                       key_usage=[True, False, True, False, False,
                                  False, False, False, False]):
    """
    create a certificate signed with CA private_key

    Args:
        ca_bundle (inst): private key instance to sign the CA
        public_key (inst): public key for the CSR
        country (str): the country for the CSR
        state_province (str): the state or province for the CSR
        locality (str): the locality for the CSR
        orga (str): the organization for the CSR
        unit (str): the unit for the CSR
        name (str): the name for the CSR
        key_usage (list): Key Usage parameters. Indices stand for:
            [digital_signature, content_commitment, key_encipherment,
            data_encipherment, key_agreement, key_cert_sign, crl_sign,
            encipher_only, decipher_only]

    Return:
        ssl certificate object
    """
    attributes = []

    if country:
        attributes.append(x509.NameAttribute(NameOID.COUNTRY_NAME, country))
    if state_province:
        attributes.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME,
                                             state_province))
    if locality:
        attributes.append(x509.NameAttribute(NameOID.LOCALITY_NAME, locality))
    if orga:
        attributes.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga))
    if unit:
        attributes.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME,
                                             unit))
    if name:
        attributes.append(x509.NameAttribute(NameOID.COMMON_NAME, name))

    subject = x509.Name(attributes)

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        ca_bundle.cert.subject
    ).public_key(
        public_key
    ).not_valid_before(
        # note to future people
        # sometimes your desktop server will have a time
        # deviation from the server, to avoid the certificate
        # invalidation we introduce a little buffer in the
        # time
        datetime.datetime.utcnow() + datetime.timedelta(minutes=-10)
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_after(
        # Our certificate will be valid for 1800 days
        datetime.datetime.utcnow() + datetime.timedelta(days=1800))

    alt_names = []

    if hosts:
        alt_names.extend(x509.DNSName(host) for host in hosts)

    if ips:
        alt_names.extend(x509.IPAddress(ipaddress.IPv4Address(ip))
                         for ip in ips)

    cert = cert.add_extension(
        x509.KeyUsage(*key_usage),
        critical=True
    )

    cert = cert.add_extension(
        x509.ExtendedKeyUsage(
            [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
             x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]
        ),
        critical=False
    )

    cert = cert.add_extension(x509.BasicConstraints(False, None),
                              critical=True)
    cert = cert.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(public_key),
        critical=False)

    cert = cert.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(
            ca_bundle.cert.public_key()), critical=False)

    if alt_names:
        cert = cert.add_extension(
            x509.SubjectAlternativeName(alt_names),
            critical=False)

    cert = cert.sign(ca_bundle.key, hashes.SHA256(), default_backend())

    return cert


def b64_key(key):
    """encode private bytes of a key to base64"""

    bytes_args = dict(encoding=serialization.Encoding.PEM,
                      format=serialization.PrivateFormat.TraditionalOpenSSL,
                      encryption_algorithm=serialization.NoEncryption())

    key_bytes = key.private_bytes(**bytes_args)

    return base64.b64encode(key_bytes).decode()


def b64_cert(cert):
    """encode public bytes of a cert to base64"""
    return base64.b64encode(
        cert.public_bytes(serialization.Encoding.PEM)).decode()


def write_key(key, passwd=None, filename="key.pem"):  # pragma: no coverage
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
    with open(filename, "wb") as fh:
        fh.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=enc_algo,))


def write_cert(cert, filename):  # pragma: no coverage
    """
    Write the certifiacte instance to the file as ASCII string

    Args:

       cert (SSL certificate instance)
       filename (str): the file to write
    """

    with open(filename, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


def discovery_hash(cert):
    """
    calculate a discovery hash based on the cert's public key
    """
    pub_key = cert.public_key()
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(pub_key.public_bytes(
        serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo))
    return digest.finalize().hex()


class CertBundle:
    """
    a simple class to hold a certifacte data with its own key
    """

    @classmethod
    def create_signed(cls, ca_bundle, country, state, locality,
                      orga, unit, name, hosts, ips,
                      key_usage=[True, False, True, False, False,
                                 False, False, False, False]):

        """
        create a sign certificate
        """
        key = create_key()
        cert = create_certificate(ca_bundle,
                                  key.public_key(),
                                  country,
                                  state,
                                  locality,
                                  orga,
                                  unit,
                                  name,
                                  hosts,
                                  ips,
                                  key_usage)

        return cls(key, cert)

    @classmethod
    def read_bundle(cls, key, cert):
        """
        read a certificate bundle from file system
        """
        key, cert = read_key(key), read_cert(cert)
        return cls(key, cert)

    def __init__(self, key, cert):
        self.key = key
        self.cert = cert

    def save(self, name, directory, key_suffix="-key.pem",
             cert_suffix=".pem"):
        """
        save a certificate bundle to the file system
        """
        if not os.path.exists(directory):
            os.mkdir(directory)

        if not os.path.isfile(os.path.join(directory, name + key_suffix)):
            write_key(self.key, filename=os.path.join(directory, name + key_suffix))

        if not os.path.isfile(os.path.join(directory, name + cert_suffix)):
            write_cert(self.cert, os.path.join(directory, name + cert_suffix))


def read_cert(cert):  # pragma: no coverage
    """
    read SSL certificate from path

    Args:
        cert (str) - path to a cert on a file system

    Return:
        cert (inst) - a certificate instance
    """

    with open(cert, "rb") as fh:
        cert = x509.load_pem_x509_certificate(
            fh.read(), default_backend())
    return cert


def read_key(key):  # pragma: no coverage
    """
    read SSL key from path

    Args:
        key (str) - path to a key on a file system

    Return:
        private_key (inst) - a private key instance
    """
    with open(key, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend())
    return private_key


def create_certs(config, names, ips, write=True, ca_bundle=None):
    """
    create new certificates, useful for replacing certificates
    and later for adding nodes ...
    """
    country = "DE"
    state = "Bayern"
    location = "NUE"

    if not ca_bundle:
        ca_key = create_key()
        ca_cert = create_ca(ca_key, ca_key.public_key(), country,
                            state, location, "Kubernetes", "CDA-PI",
                            "kubernetes")
        ca_bundle = CertBundle(ca_key, ca_cert)

    else:
        ca_key = ca_bundle.key
        ca_cert = ca_bundle.cert

    k8s_bundle = CertBundle.create_signed(ca_bundle,
                                          country,
                                          state,
                                          location,
                                          "Kubernetes",
                                          "CDA-PI",
                                          "kubernetes",
                                          names,
                                          ips)

    svc_accnt_bundle = CertBundle.create_signed(ca_bundle,
                                                country,
                                                state,
                                                location,
                                                "Kubernetes",
                                                "CDA-PI",
                                                name="service-accounts",
                                                hosts="",
                                                ips="")

    admin_bundle = CertBundle.create_signed(ca_bundle,
                                            country,
                                            state,
                                            location,
                                            "system:masters",
                                            "CDA-PI",
                                            name="admin",
                                            hosts="",
                                            ips=""
                                            )

    kubelet_bundle = CertBundle.create_signed(ca_bundle,
                                              country,
                                              state,
                                              location,
                                              "system:masters",
                                              "CDA-PI",
                                              name="kubelet",
                                              hosts=names,
                                              ips=ips
                                              )

    nodes = []
    node_bundles = []
    node_ip = None
    for node in nodes:
        node_bundles.append(CertBundle.create_signed(ca_bundle,
                                                     country,
                                                     state,
                                                     location,
                                                     "system:nodes",
                                                     "CDA-PI",
                                                     name="system:node:%s" % node,  # noqa
                                                     hosts=[node],
                                                     ips=[node_ip]))

    LOGGER.debug("Done creating all certificates")
    if write:  # pragma: no coverage
        cert_dir = "-".join(("certs", config["cluster-name"]))

        if not os.path.exists(cert_dir):
            os.mkdir(cert_dir)

        write_key(ca_key, filename=cert_dir + "/ca-key.pem")
        write_cert(ca_cert, cert_dir + "/ca.pem")

        k8s_bundle.save("kubernetes", cert_dir)
        svc_accnt_bundle.save("service-account", cert_dir)
        admin_bundle.save("admin", cert_dir)
        kubelet_bundle.save("kubelet", cert_dir)

    return {'ca': ca_bundle, 'k8s': k8s_bundle,
            'service-account': svc_accnt_bundle,
            'admin': admin_bundle,
            'kubelet': kubelet_bundle}
