import datetime
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography import utils


def create_key(size, public_exponent):
    key = rsa.generate_private_key(
        public_exponent=public_exponent,
        key_size=size,
        backend=default_backend()
    )
    return key


def create_certificate(private_key, public_key, country,
                       state_province, locality, orga, name, hosts):

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
        x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])



    ca_cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        public_key
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_after(
        # Our certificate will be valid for 1800 days
        datetime.datetime.utcnow() + datetime.timedelta(days=1800)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(host)] for host in hosts),
        critical=False,
        # Sign our certificate with our private key
    ).sign(private_key, hashes.SHA256(), default_backend())

ca_key = create_key()
ca_cert = create_certificate(ca_key, ca_key.public_key(), "DE", "BY", "NUE", "noris-network", "CA", ["CA"])


k8s_key = create_key()
ca_cert = create_certificate(ca_key, k8s_key.public_key(), "DE", "BY", "NUE", "noris-network", "Kubernetes", hosts)

