"""
create certificates for etcd according to kubeadm specs.

https://kubernetes.io/docs/reference/setup-tools/kubeadm/kubeadm-config
"""
import argparse
import os

from koris.ssl import CertBundle, create_key, create_ca

parser = argparse.ArgumentParser(description='create ssl certs + keys for etcd')
parser.add_argument('--ips', metavar='ips', type=str, nargs='+',
                    help='the ips')
parser.add_argument('--hosts', metavar='hosts', type=str, nargs='+',
                    help='the host names')


args = parser.parse_args()


# create a self signed ca
key = create_key(size=2048)
ca = create_ca(key, key.public_key(),
               "DE", "BY", "NUE", "Kubernetes", "CDA-PI",
               "kubernetes")

ca_bundle = CertBundle(key, ca)
# create a self signed ca for etcd
etcd_key = create_key(size=2048)
etcd_ca = create_ca(key, key.public_key(),
                    "DE", "BY", "NUE", "Kubernetes", "CDA-PI",
                    "kubernetes")

ca_bundle = CertBundle(key, ca)
etcd_ca_bundle = CertBundle(etcd_key, etcd_ca)


# for each etcd host create a certificate and key for peer connection
# for each etcd host create a certificate and key for server

for host, ip in zip(args.hosts, args.ips):
    os.makedirs("%s/kubernetes/pki/etcd/" % host, exist_ok=True)
    ca_bundle.save("ca", "%s/kubernetes/pki/" % host,
                   key_suffix=".key", cert_suffix=".crt")
    etcd_ca_bundle.save("ca", "%s/kubernetes/pki/etcd" % host,
                        key_suffix=".key", cert_suffix=".crt")
    peer = CertBundle.create_signed(ca_bundle,
                                    "",  # country
                                    "",  # state
                                    "",  # locality
                                    "",  # orga
                                    "",  # unit
                                    "kubernetes",  # name
                                    [host, 'localhost', host],
                                    [ip, '127.0.0.1', ip]
                                    )
    peer.save("peer", "%s/kubernetes/pki/etcd" % host,
              key_suffix=".key", cert_suffix=".crt")

    server = CertBundle.create_signed(ca_bundle,
                                      "",  # country
                                      "",  # state
                                      "",  # locality
                                      "",  # orga
                                      "",  # unit
                                      host,  # name CN
                                      [host, 'localhost', host],
                                      [ip, '127.0.0.1', ip]
                                      )
    server.save("server", "%s/kubernetes/pki/etcd" % host,
                key_suffix=".key", cert_suffix=".crt")

    health = CertBundle.create_signed(ca_bundle,
                                      "",  # country
                                      "",  # state
                                      "",  # locality
                                      "system:masters",  # orga
                                      "",  # unit
                                      'kube-etcd-healthcheck-client',  # name CN
                                      None,
                                      None
                                      )
    health.save("healthcheck-client",
                "%s/kubernetes/pki/etcd/" % host,
                key_suffix=".key", cert_suffix=".crt")
