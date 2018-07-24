import asyncio
import os
import sys

from .hue import red

from .ssl import (create_key,
                  create_ca,
                  write_key, write_cert, CertBundle)
from .util import get_kubeconfig_yaml, host_names


def delete_cluster(config, nova, neutron):
    print(red("You are about to destroy your cluster!!!"))
    print(red("Are you really sure ? [y/N]"))
    ans = input(red("ARE YOU REALLY SURE???"))

    if ans.lower() == 'y':
        cluster_suffix = "-%s" % config['cluster-name']
        servers = [server for server in nova.servers.list() if
                   server.name.endswith(cluster_suffix)]

        async def del_server(server):
            await asyncio.sleep(1)
            nics = [nic for nic in server.interface_list()]
            server.delete()
            [neutron.delete_port(nic.id) for nic in nics]
            print("deleted %s ..." % server.name)

        loop = asyncio.get_event_loop()
        tasks = [loop.create_task(del_server(server)) for server in servers]

        if tasks:
            loop.run_until_complete(asyncio.wait(tasks))
        loop.close()
    else:
        sys.exit(1)


def write_kubeconfig(config, etcd_cluster_info, admin_token, write=False):
    master = host_names("master", config["n-masters"],
                        config['cluster-name'])[0]
    username = "admin"
    master_uri = "http://%s:3210" % master
    kubeconfig = get_kubeconfig_yaml(master_uri, username, admin_token, write,
                                     encode=False)
    if write:
        filename = "admin.conf"
        with open(filename, "w") as f:
            f.write(kubeconfig)


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
                            state, location, "Kubernetes", "CDA\PI",
                            "kubernetes")
        ca_bundle = CertBundle(ca_key, ca_cert)

    else:
        ca_key = ca_bundle.key
        ca_cert = ca_bundle.cert

    k8s_bundle = CertBundle.create_signed(ca_key,
                                          country,
                                          state,
                                          location,
                                          "Kubernetes",
                                          "CDA\PI",
                                          "kubernetes",
                                          names,
                                          ips)

    svc_accnt_bundle = CertBundle.create_signed(ca_key,
                                                country,
                                                state,
                                                location,
                                                "Kubernetes",
                                                "CDA\PI",
                                                name="service-accounts",
                                                hosts="",
                                                ips="")

    admin_bundle = CertBundle.create_signed(ca_key,
                                            country,
                                            state,
                                            location,
                                            "system:masters",
                                            "CDA\PI",
                                            name="admin",
                                            hosts="",
                                            ips=""
                                            )

    kubelet_bundle = CertBundle.create_signed(ca_key,
                                              country,
                                              state,
                                              location,
                                              "system:masters",
                                              "CDA\PI",
                                              name="kubelet",
                                              hosts=names,
                                              ips=ips
                                              )

    nodes = []
    node_bundles = []
    node_ip = None
    # todo: add node_ip
    for node in nodes:
        node_bundles.append(CertBundle.create_signed(ca_key,
                                                     country,
                                                     state,
                                                     location,
                                                     "system:nodes",
                                                     "CDA\PI",
                                                     name="system:node:%s" % node,  # noqa
                                                     hosts=[node],
                                                     ips=[node_ip]))

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
