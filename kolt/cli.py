import asyncio
import sys

from .hue import red

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
