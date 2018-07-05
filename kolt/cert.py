import datetime
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography import utils

# create ca
size=2048 
public_exponent=65537

country = "DE"
state_province = "BY"
locality = "NUE"
orga = "noris-network"
name = "Kubernetes"

hosts = ["node-1-nude", "node-2-nude", "node-3-nude",
         "etcd-1-nude", "etcd-2-nude", "etcd-3-nude"
         "master-1-nude", "master-2-nude", "master-3-nude"]


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


ca_key = rsa.generate_private_key(
    public_exponent=public_exponent,
    key_size=size,
    backend=default_backend()
)


write_key(ca_key, filename="ca-key.pem")


subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, country),
    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
    x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
    x509.NameAttribute(NameOID.COMMON_NAME, "CA"),
])



ca_cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    ca_key.public_key()
).not_valid_before(
    datetime.datetime.utcnow()
).serial_number(
    x509.random_serial_number()
).not_valid_after(
    # Our certificate will be valid for 1800 days
    datetime.datetime.utcnow() + datetime.timedelta(days=1800)
).add_extension(
    x509.SubjectAlternativeName([x509.DNSName("Kubernetes.CA")]),
    critical=False,
    # Sign our certificate with our private key
).sign(ca_key, hashes.SHA256(), default_backend())

write_cert(ca_cert, "ca.pem")

# end of CA creation

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, country),
    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state_province),
    x509.NameAttribute(NameOID.LOCALITY_NAME, locality),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, orga),
    x509.NameAttribute(NameOID.COMMON_NAME, "Kubernetes"),
])

k8s_key = rsa.generate_private_key(
    public_exponent=public_exponent,
    key_size=size,
    backend=default_backend()
)


write_key(k8s_key, filename="kubernetes-key.pem")

k8s_cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    k8s_key.public_key()
).not_valid_before(
    datetime.datetime.utcnow()
).serial_number(
    x509.random_serial_number()
).not_valid_after(
    # Our certificate will be valid for 1800 days
    datetime.datetime.utcnow() + datetime.timedelta(days=1800)
).add_extension(
    x509.SubjectAlternativeName(x509.DNSName(host) for host in hosts),
    critical=False,
    # Sign our certificate with our private key
).sign(ca_key, hashes.SHA256(), default_backend())

write_cert(k8s_cert, "kubernetes.pem")
