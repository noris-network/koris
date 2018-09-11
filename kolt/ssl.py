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

from kolt.util.util import get_logger

logger = get_logger(__name__)


def create_key(size=2048, public_exponent=65537):
    key = rsa.generate_private_key(
        public_exponent=public_exponent,
        key_size=size,
        backend=default_backend()
    )
    return key


def create_ca(private_key, public_key, country,
              state_province, locality, orga, unit, name):
    issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga.capitalize()),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name.capitalize()),
    ])

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga.capitalize()),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name.capitalize()),
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
        x509.KeyUsage(False, False, False, False, False, True,
                      True, False, False),
        critical=True)

    cert = cert.add_extension(x509.BasicConstraints(True, 2), critical=True)
    cert = cert.add_extension(
        x509.SubjectKeyIdentifier.from_public_key(public_key),
        critical=False)

    cert = cert.add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key),
        critical=False)

    cert = cert.sign(private_key, hashes.SHA256(), default_backend())

    return cert


def create_certificate(ca_bundle, public_key, country,
                       state_province, locality, orga, unit, name, hosts, ips):

    issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga.capitalize()),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name.capitalize()),
    ])

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga.capitalize()),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unit),
        x509.NameAttribute(NameOID.COMMON_NAME, name.capitalize()),
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

    alt_names = []

    if hosts:
        alt_names.extend(x509.DNSName(host) for host in hosts)

    if ips:
        alt_names.extend(x509.IPAddress(ipaddress.IPv4Address(ip))
                         for ip in ips)

    cert = cert.add_extension(
        x509.KeyUsage(
            True, False, True, False, False, False, False, False, False
        ),
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
        x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_bundle.cert.public_key()),  # noqa
        critical=False)

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
    with open(filename, "wb") as f:
        f.write(key.private_bytes(
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

    with open(filename, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


class CertBundle:

    @classmethod
    def create_signed(cls, ca_bundle, country, state, locality,
                      orga, unit, name, hosts, ips):

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
                                  ips)

        return cls(key, cert)

    @classmethod
    def read_bundle(cls, key, cert):
        key, cert = read_key(key), read_cert(cert)
        return cls(key, cert)

    def __init__(self, key, cert):
        self.key = key
        self.cert = cert

    def save(self, name, directory):
        write_key(self.key,
                  filename=os.path.join(directory, name + "-key.pem"))
        write_cert(self.cert, os.path.join(directory, name + ".pem"))


def read_cert(cert):  # pragma: no coverage
    with open(cert, "rb") as f:
        cert = x509.load_pem_x509_certificate(
            f.read(), default_backend())
    return cert


def read_key(key):  # pragma: no coverage
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
    # todo: add node_ip
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

    logger.debug("Done creating all certificates")
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
