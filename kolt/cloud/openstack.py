import asyncio
import base64
import copy
import os
import sys
import textwrap
import time
import uuid

from novaclient import client as nvclient
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient

from novaclient.exceptions import (NotFound as NovaNotFound,
                                   ClientException as NovaClientException)

from keystoneauth1 import identity
from keystoneauth1 import session

from kolt.util.hue import red, info, que, yellow
from kolt.util.util import (get_logger, Server, get_host_zones, host_names)

logger = get_logger(__name__)


async def create_volume(cinder, image, zone, klass, size=25):
    bdm_v2 = {
        "boot_index": 0,
        "source_type": "volume",
        "volume_size": str(size),
        "destination_type": "volume",
        "delete_on_termination": True}

    v = cinder.volumes.create(size, name=uuid.uuid4(), imageRef=image.id,
                              availability_zone=zone,
                              volume_type=klass)

    while v.status != 'available':
        await asyncio.sleep(1)
        v = cinder.volumes.get(v.id)

    logger.debug("created volume %s %s" % (v, v.volume_type))

    if v.bootable != 'true':
        v.update(bootable=True)
        # wait for mark as bootable
        await asyncio.sleep(2)

    volume_data = copy.deepcopy(bdm_v2)
    volume_data['uuid'] = v.id

    return volume_data


async def create_instance_with_volume(name, zone, flavor, image,
                                      keypair, secgroups, userdata, hosts,
                                      nova=None,
                                      neutron=None,
                                      cinder=None,
                                      nics=None,
                                      volume_klass=""
                                      ):
    try:
        print(que("Checking if %s does not already exist" % name))
        server = nova.servers.find(name=name)
        ip = server.interface_list()[0].fixed_ips[0]['ip_address']
        print(info("This machine already exists ... skipping"))
        hosts[name] = (ip)
        return
    except NovaNotFound:
        print(info("Okay, launching %s" % name))
    except IndexError:
        logger.debug("Server found in weired state witout IP ... recreating")
        server.delete()

    volume_data = await create_volume(cinder, image, zone, volume_klass)

    try:
        print("Creating instance %s... " % name)
        instance = nova.servers.create(name=name,
                                       availability_zone=zone,
                                       image=None,
                                       key_name=keypair.name,
                                       flavor=flavor,
                                       nics=nics, security_groups=secgroups,
                                       block_device_mapping_v2=[volume_data],
                                       userdata=userdata,
                                       )

    except NovaClientException as E:
        print(info(red("Something weired happend, I so I didn't create %s" %
                       name)))
        print(info(yellow(E.message)))
        # TODO: clean volume and nic here
    except KeyboardInterrupt:
        print(info(red("Oky doky, stopping as you interrupted me ...")))
        print(info(red("Cleaning after myself")))
        # TODO: clean volume and nic here
        # clean volume
        cinder.volumes.delete(volume_data["id"])

    inst_status = instance.status
    print("waiting for 5 seconds for the machine to be launched ... ")
    await asyncio.sleep(5)

    while inst_status == 'BUILD':
        print("Instance: " + instance.name + " is in " + inst_status +
              " state, sleeping for 5 seconds more...")
        await asyncio.sleep(5)
        instance = nova.servers.get(instance.id)
        inst_status = instance.status

    print("Instance: " + instance.name + " is in " + inst_status + " state")

    ip = instance.interface_list()[0].fixed_ips[0]['ip_address']
    print("Instance booted! Name: " + instance.name + " Status: " +
          instance.status + ", IP: " + ip)

    hosts[name] = (ip)


def create_loadbalancer(client, network, name, master_ips, provider='octavia',
                        **kwargs):
    """Create a load balancer for the kuberentes api server

    The API is async, so we need to check `provisioning_status` of the LB
    created.

    Args:
        client (neutronclient.v2_0.client.Client)
        network (str): The network name for the load balancer
        name (str): The loadbalancer name
        master_ips (list): A list of the master IP addresses
        provider (str): The Openstack provider for loadbalancing

    Kwargs:
        subnet (str): if given this subnet will be used, in any other case
          the last one will be used.

    Returns:
        lb (dict): A dictionary containing the information about the lb created

    """
    # see examle of how to create an LB
    # https://developer.openstack.org/api-ref/load-balancer/v2/index.html#id6

    if 'subnet' in kwargs:
        subnet_id = client.find_resource('subnet', kwargs['subnet'])['id']
    else:
        subnet_id = client.list_subnets()['subnets'][-1]['id']

    lb = client.create_loadbalancer({'loadbalancer':
                                     {'provider': provider,
                                      'vip_subnet_id': subnet_id,
                                      'name': "%s-lb" % name
                                      }
                                     })
    lb = lb['loadbalancer']
    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(2)
    logger.debug("Created loadbalancer ...")
    listener = client.create_listener({'listener':
                                       {"loadbalancer_id":
                                        lb['id'],
                                        "protocol": "HTTPS",
                                        "protocol_port": 6443,
                                        'admin_state_up': True,
                                        'name': '%s-listener' % name
                                        }})

    logger.debug("added listener ...")
    lb = client.list_loadbalancers(id=lb['id'])['loadbalancers'][0]

    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(2)

    pool = client.create_lbaas_pool(
        {"pool": {"lb_algorithm": "SOURCE_IP",
                  "listener_id": listener["listener"]['id'],
                  "loadbalancer_id": lb["id"],
                  "protocol": "HTTPS",
                  "name": "%s-pool" % name},
         })

    logger.debug("added pool ...")
    lb = client.list_loadbalancers(id=lb['id'])['loadbalancers'][0]

    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(0.5)

    client.create_lbaas_healthmonitor(
        {'healthmonitor':
            {"delay": 5, "timeout": 3, "max_retries": 3, "type": "TCP",
             "pool_id": pool['pool']['id'],
             "name": "%s-health" % name}})

    logger.debug("added health monitor ...")

    lb = client.list_loadbalancers(id=lb['id'])['loadbalancers'][0]

    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(0.5)

    for ip in master_ips:
        client.create_lbaas_member(pool['pool']['id'],
                                   {'member': {'subnet_id': subnet_id,
                                               'protocol_port': 6443,
                                               'address': ip,
                                               }})

        lb = client.list_loadbalancers(id=lb['id'])['loadbalancers'][0]
        while lb['provisioning_status'] != 'ACTIVE':
            lb = client.list_loadbalancers(id=lb['id'])
            lb = lb['loadbalancers'][0]
            time.sleep(0.5)

        logger.debug("added pool member %s ..." % ip)

    return lb


def delete_loadbalancer(client, network, name):
    try:
        client.delete_lbaas_healthmonitor(
            client.list_lbaas_healthmonitors(
                {"name": "%s-health" % name})['healthmonitors'][0]['id'])
    except IndexError:
        pass
    lb = client.list_loadbalancers({"name": "nude-lb"})['loadbalancers'][0]

    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(0.5)

    while True:
        try:
            client.delete_lbaas_pool(
                client.list_lbaas_pools(
                    {"name": "%s-pool" % name})['pools'][0]['id'])
        except IndexError:
            break
        except Exception as E:
            print("Error while deleting pool: %s " % E)
            continue

    lb = client.list_loadbalancers({"name": "nude-lb"})['loadbalancers'][0]

    while lb['provisioning_status'] != 'ACTIVE':
        lb = client.list_loadbalancers(id=lb['id'])
        lb = lb['loadbalancers'][0]
        time.sleep(0.5)

    while True:
        try:
            client.delete_listener(
                client.list_listeners(
                    {"name": "%s-listener" % name})['listeners'][0]['id']
            )
            break
        except IndexError:
            break

        except Exception as E:
            print("Error while deleting listener: %s " % E)
            continue


def read_os_auth_variables(trim=True):
    """
    Automagically read all OS_* variables and
    yield key: value pairs which can be used for
    OS connection
    """
    d = {}
    for k, v in os.environ.items():
        if k.startswith("OS_"):
            d[k[3:].lower()] = v
    if trim:
        not_in_default_rc = ('interface', 'region_name',
                             'identity_api_version', 'endpoint_type',
                             )

        [d.pop(i) for i in not_in_default_rc if i in d]

    return d


def get_clients():
    try:
        auth = identity.Password(**read_os_auth_variables())
        sess = session.Session(auth=auth)
        nova = nvclient.Client('2.1', session=sess)
        neutron = ntclient.Client(session=sess)
        cinder = cclient.Client('3.0', session=sess)
    except TypeError:
        print(red("Did you source your OS rc file in v3?"))
        print(red("If your file has the key OS_ENDPOINT_TYPE it's the"
                  " wrong one!"))
        sys.exit(1)
    except KeyError:
        print(red("Did you source your OS rc file?"))
        sys.exit(1)

    return nova, neutron, cinder


class OSCloudConfig:

    def __init__(self, subnet_id=None):
        os_vars = read_os_auth_variables(trim=False)
        self.subnet_id = subnet_id
        self.username = os_vars['username']
        self.password = os_vars['password']
        self.auth_url = os_vars['auth_url']
        self.__dict__.update(os_vars)
        self.tenant_id = self.project_id
        self.__dict__.pop('project_id')
        del os_vars

    def __str__(self):
        global_ = textwrap.dedent("""
        [Global]
        username=%s
        password=%s
        auth-url=%s
        tenant-id=%s
        domain-name=%s
        region=%s
        """ % (self.username, self.password, self.auth_url,
               self.tenant_id, self.user_domain_name,
               self.region_name)).lstrip()
        lb = ""
        if self.subnet_id:
            lb = textwrap.dedent("""
            [LoadBalancer]
            subnet-id=%s
            #use-octavia=true
            """ % (self.subnet_id))

        return global_ + lb

    def __bytes__(self):
        return base64.b64encode(str(self).encode())


class OSClusterInfo:

    def __init__(self, nova_client, neutron_client, config):

        self.keypair = nova_client.keypairs.get(config['keypair'])
        self.image = nova_client.glance.find_image(config['image'])
        self.node_flavor = nova_client.flavors.find(name=config['node_flavor'])
        self.master_flavor = nova_client.flavors.find(
            name=config['master_flavor'])
        secgroup = neutron_client.find_resource('security_group',
                                                config['security_group'])
        self.secgroups = [secgroup['id']]
        self.net = neutron_client.find_resource("network", config["private_net"])  # noqa

        if 'subnet' in config:
            self.subnet_id = neutron_client.find_resource('subnet',
                                                          config['subnet'])['id']  # noqa
        else:
            self.subnet_id = neutron_client.list_subnets()['subnets'][-1]['id']

        self.name = config['cluster-name']
        self.n_nodes = config['n-nodes']
        self.n_masters = config['n-masters']
        self.azones = config['availibility-zones']
        self.storage_class = config['storage_class']

        self._novaclient = nova_client
        self._neutronclient = neutron_client

    def _status(self, names):
        """
        Finds if all mahcines in the group exists
        """
        for name in names:
            try:
                _server = self._novaclient.servers.find(name=name)
                yield Server(_server.name, _server.interface_list(),
                             server=_server)

            except NovaNotFound:
                port = self._neutronclient.create_port(
                    {"port": {"admin_state_up": True,
                              "network_id": self.net['id'],
                              "security_groups": self.secgroups}})

                yield Server(name, [port])

    @property
    def nodes_status(self):
        """
        Finds if all work nodes exists
        """
        return list(self._status(self.nodes_names))

    @property
    def management_status(self):
        """
        Finds if all mangament nodes exists
        """
        return list(self._status(self.management_names))

    @property
    def nodes_names(self):
        return host_names("node", self.n_nodes, self.name)

    @property
    def management_names(self):
        return host_names("master", self.n_masters, self.name)

    def master_args_builder(self, user_data, hosts):

        return [self.master_flavor, self.image, self.keypair, self.secgroups,
                user_data, hosts]

    def node_args_builder(self, user_data, hosts):

        return [self.node_flavor, self.image, self.keypair, self.secgroups,
                user_data, hosts]

    def distribute_management(self):
        return list(get_host_zones(self.management_names, self.azones))

    def distribute_nodes(self):
        return list(get_host_zones(self.nodes_names, self.azones))

    def assign_nics_to_management(self, management_zones, nics):
        for idx, nic in enumerate(nics):
            management_zones[idx].nic = [{'net-id': self.net['id'],
                                         'port-id': nic['port']['id']}]

    def assign_nics_to_nodes(self, nodes_zones, nics):
        for idx, nic in enumerate(nics):
            nodes_zones[idx].nic = [{'net-id': self.net['id'],
                                     'port-id': nic['port']['id']}]
