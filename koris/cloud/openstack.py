"""
functions and classes to interact with openstack
"""

import asyncio
import base64
import copy
import logging
import os
import re
import sys
import textwrap

from functools import lru_cache

import novaclient
from novaclient import client as nvclient
from novaclient.exceptions import (NotFound as NovaNotFound)  # noqa

import cinderclient
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient
from neutronclient.common.exceptions import Conflict as NeutronConflict
from neutronclient.common.exceptions import StateInvalidClient
from neutronclient.common.exceptions import NotFound

from keystoneauth1 import identity
from keystoneauth1 import session

from koris.cloud import OpenStackAPI
from koris.util.hue import (red, info, yellow)  # pylint: disable=no-name-in-module
from koris.util.util import (get_logger, host_names,
                             retry)

LOGGER = get_logger(__name__, level=logging.DEBUG)

if getattr(sys, 'frozen', False):
    def monkey_patch():
        """monkey patch get available versions, because the original
        code uses __file__ which is not available in frozen build"""
        return ['2', '1']
    novaclient.api_versions.get_available_major_versions = monkey_patch

    def monkey_patch_cider():
        """the same spiel for cinder"""
        return ['3']
    cinderclient.api_versions.get_available_major_versions = monkey_patch_cider  # noqa


def remove_cluster(config, nova, neutron, cinder):
    """
    Delete a cluster from OpenStack
    """
    cluster_info = OSClusterInfo(nova, neutron, cinder, config)
    cp_hosts = cluster_info.distribute_management()
    workers = cluster_info.distribute_nodes()

    tasks = [host.delete(neutron) for host in cp_hosts]
    tasks += [host.delete(neutron) for host in workers]
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.wait(tasks))
    lbinst = LoadBalancer(config)
    lbinst.delete(neutron)
    connection = OpenStackAPI.connect()
    secg = connection.list_security_groups(
        {"name": '%s-sec-group' % config['cluster-name']})
    if secg:
        for sg in secg:
            for rule in sg.security_group_rules:
                connection.delete_security_group_rule(rule['id'])

            for port in connection.list_ports():
                if sg.id in port.security_groups:
                    connection.delete_port(port.id)
    connection.delete_security_group(
        '%s-sec-group' % config['cluster-name'])

    # delete volumes

    loop.close()
    for vol in cinder.volumes.list():
        try:
            if config['cluster-name'] in vol.name and vol.status != 'in-use':
                vol.delete()
            except TypeError:
                continue


class BuilderError(Exception):
    """Raise a custom error if the build fails"""


class Instance:
    """
    Create an Openstack Server with an attached volume
    """

    def __init__(self, cinder, nova, name, network, zone, role,
                 volume_config):
        self.cinder = cinder
        self.nova = nova
        self.name = name
        self.network = network
        self.zone = zone
        self.volume_size = volume_config.get('size', '25')
        self.volume_class = volume_config.get('class')
        self.volume_img = volume_config.get('image')
        self.role = role
        self._ports = []
        self._ip_address = None
        self.exists = False

    @property
    def nics(self):
        """return all network interfaces attached to the instance"""
        return [{'net-id': self.network['id'],
                 'port-id': self._ports[0]['port']['id']}]

    @property
    def ip_address(self):
        """return the IP address of the first NIC"""
        try:
            return self._ports[0]['port']['fixed_ips'][0]['ip_address']
        except TypeError:
            return self._ports[0].fixed_ips[0]['ip_address']
        except IndexError:
            raise AttributeError("Instance has no ports attached")

    def attach_port(self, netclient, net, secgroups):
        """associate a network port with an instance"""
        port = netclient.create_port({"port": {"admin_state_up": True,
                                               "network_id": net,
                                               "security_groups": secgroups}})
        self._ports.append(port)

    async def _create_volume(self):  # pragma: no coverage
        bdm_v2 = {
            "boot_index": 0,
            "source_type": "volume",
            "volume_size": str(self.volume_size),
            "destination_type": "volume",
            "delete_on_termination": True}

        vol = self.cinder.volumes.create(self.volume_size,
                                         name=self.name,
                                         imageRef=self.volume_img.id,
                                         availability_zone=self.zone,
                                         volume_type=self.volume_class)

        while vol.status != 'available':
            await asyncio.sleep(1)
            vol = self.cinder.volumes.get(vol.id)

        LOGGER.debug("created volume %s %s", vol, vol.volume_type)

        if vol.bootable != 'true':
            vol.update(bootable=True)
            # wait for mark as bootable
            await asyncio.sleep(2)

        volume_data = copy.deepcopy(bdm_v2)
        volume_data['uuid'] = vol.id

        return volume_data

    async def create(self, flavor, secgroups, keypair, userdata):  # pragma: no coverage
        """
        Boot the instance on openstack
        returns the OpenStack instance
        """
        if self.exists:
            return self

        volume_data = await self._create_volume()

        try:
            LOGGER.info("Creating instance %s... ", self.name)
            instance = self.nova.servers.create(
                name=self.name,
                availability_zone=self.zone,
                image=None,
                key_name=keypair.name,
                flavor=flavor,
                nics=self.nics, security_groups=secgroups,
                block_device_mapping_v2=[volume_data],
                userdata=userdata
            )
        except (Exception) as err:
            print(info(red("Something weired happend, I so I didn't create %s" %
                           self.name)))
            print(info(red("Removing cluser ...")))
            print(info(yellow("The exception is", str((err)))))
            raise BuilderError(str(err))

        inst_status = instance.status
        print("waiting for 5 seconds for the machine to be launched ... ")
        await asyncio.sleep(5)

        while inst_status == 'BUILD':
            LOGGER.info(
                "Instance: %s is in in %s state, sleeping for 5 more seconds",
                instance.name, inst_status)
            await asyncio.sleep(5)
            instance = self.nova.servers.get(instance.id)
            inst_status = instance.status

        print("Instance: " + instance.name + " is in " + inst_status + " state")

        self._ip_address = instance.interface_list()[0].fixed_ips[0]['ip_address']
        LOGGER.info(
            "Instance booted! Name: %s, IP: %s, Status : %s",
            self.name, instance.status, self._ip_address)

        self.exists = True
        return self

    async def delete(self, netclient):
        """stop and terminate an instance"""
        try:
            server = self.nova.servers.find(name=self.name)
            nics = [nic for nic in server.interface_list()]
            server.delete()
            list(netclient.delete_port(nic.id) for nic in nics)
            LOGGER.info("deleted %s ...", server.name)
        except NovaNotFound:
            pass


class LoadBalancer:  # pragma: no coverage

    """
    A class to create a LoadBalancer in OpenStack.

    Openstack allows one to create a loadbalancer and configure it later.
    Thus we create a LoadBalancer, so we have it's IP. The IP
    of the LoadBalancer, is then stored in the SSL certificates.
    During the boot of the machines, we configure the LoadBalancer.
    """

    def __init__(self, config):
        self.floatingip = config.get('loadbalancer', {}).get('floatingip', '')
        if not self.floatingip:
            LOGGER.warning(info(yellow("No floating IP, I hope it's OK")))
        self.name = "%s-lb" % config['cluster-name']
        self.subnet = config.get('subnet')
        # these attributes are set after creation
        self.pool = None
        self._id = None
        self._subnet_id = None
        self._data = None
        self._existing_floating_ip = None
        self.members = []

    async def configure(self, client, master_ips):
        """
        Configure a load balancer created in earlier step

        Args:
            master_ips (list): A list of the master IP addresses

        """
        if not self._data['listeners']:
            listener = self._add_listener(client)
            listener_id = listener["listener"]['id']
            LOGGER.info("Added listener ...")
        else:
            LOGGER.info("Reusing listener ...")
            listener_id = self._data['listeners'][0]['id']

        if not self._data['pools']:
            pool = self._add_pool(client, listener_id)
            LOGGER.info("Added pool ...")
        else:
            LOGGER.info("Reusing pool ...")
            LOGGER.info("Removing all members ...")
            pool = client.list_lbaas_pools(id=self._data['pools'][0]['id'])
            pool = pool['pools'][0]
            for member in pool['members']:
                self._del_member(client, member['id'], pool['id'])

        self.pool = pool['id']

        self.add_member(client, pool['id'], master_ips[0])
        if pool.get('healthmonitor_id'):
            LOGGER.info("Reusing existing health monitor ...")
        else:
            self._add_health_monitor(client, pool['id'])
            LOGGER.info("Added health monitor ...")

    def get_or_create(self, client, provider='octavia'):
        """
        find if a load balancer exists
        """
        lb = client.list_lbaas_loadbalancers(retrieve_all=True,
                                             name=self.name)['loadbalancers']
        if not lb or 'DELETE' in lb[0]['provisioning_status']:
            lb, fip_addr = self.create(client, provider=provider)
        else:
            LOGGER.info("Reusing an existing loadbalancer")
            self._existing_floating_ip = None
            fip_addr = self._floating_ip_address(client, lb[0])
            LOGGER.info("Loadbalancer IP: %s", fip_addr)
            lb = lb[0]
            self._id = lb['id']
            self._subnet_id = lb['vip_subnet_id']
            self._data = lb
            self.pool = lb['pools'][0]['id']

        return lb, fip_addr

    def _floating_ip_address(self, client, lb):
        floatingips = client.list_floatingips(retrieve_all=True,
                                              port_id=lb['vip_port_id'])
        if floatingips['floatingips']:
            self._existing_floating_ip = floatingips[
                'floatingips'][0]['floating_ip_address']
            fip_addr = self._existing_floating_ip
        else:
            fip_addr = self._associate_floating_ip(
                client, lb)
        return fip_addr

    def create(self, client, provider='octavia'):
        """
        provision a minimally configured LoadBalancer in OpenStack

        Args:
            client (neutronclient.v2_0.client.Client)

        Return:
            tuple (dict, str) - the dict is the load balancer information, if
            a floating IP was associated it is returned as a string. Else it's
            None.
        """
        # see examle of how to create an LB
        # https://developer.openstack.org/api-ref/load-balancer/v2/index.html#id6
        if self.subnet:
            subnet_id = client.find_resource('subnet', self.subnet)['id']
        else:
            subnet_id = client.list_subnets()['subnets'][-1]['id']

        lb = client.create_loadbalancer({'loadbalancer':
                                         {'provider': provider,
                                          'vip_subnet_id': subnet_id,
                                          'name': "%s" % self.name
                                          }})
        self._id = lb['loadbalancer']['id']
        self._subnet_id = lb['loadbalancer']['vip_subnet_id']
        self._data = lb['loadbalancer']
        LOGGER.info("created loadbalancer ...")

        fip_addr = None
        if self.floatingip:
            fip_addr = self._associate_floating_ip(client, lb['loadbalancer'])
        return lb['loadbalancer'], fip_addr

    @retry(exceptions=(NeutronConflict, NovaNotFound), backoff=1, tries=10)
    def delete(self, client):
        """
        Delete the cluster API loadbalancer

        Deletion order of LoadBalancer:
            - remove pool (LB is pending update)
            - if healthmonitor in pool, delete it first
            - remove listener (LB is pending update)
            - remove LB (LB is pending delete)
        Args:
            client (neutron client)
            suffix (str) - the suffix of the name, appended to name
        """
        lb = client.list_lbaas_loadbalancers(retrieve_all=True,
                                             name=self.name)['loadbalancers']
        if not lb or 'DELETE' in lb[0]['provisioning_status']:
            LOGGER.warning("LB %s was not found", self.name)
        else:
            lb = lb[0]
            self._id = lb['id']

            if lb['pools']:
                self._del_pool(client)
            if lb['listeners']:
                self._del_listener(client)

            self._del_loadbalancer(client)

    def _associate_floating_ip(self, client, loadbalancer):
        fip = None
        if isinstance(self.floatingip, str):  # pylint: disable=undefined-variable
            valid_ip = re.match(r"\d{2,3}\.\d{2,3}\.\d{2,3}\.\d{2,3}",  # noqa
                                self.floatingip)
            if not valid_ip:
                LOGGER.error("Please specify a valid IP address")
                sys.exit(1)
            if self._existing_floating_ip == self.floatingip:
                return self._existing_floating_ip

            fip = client.list_floatingips(
                floating_ip_address=self.floatingip)['floatingips']
            if not fip:
                LOGGER.error("Could not find %s in the pool", self.floatingip)
                sys.exit(1)
            fip = fip[0]
        if not fip:
            fips = client.list_floatingips()['floatingips']
            if not fips:
                raise ValueError(
                    "Please create a floating ip and specify it in the configuration file")  # noqa

            fnet_id = fips[0]['floating_network_id']
            fip = client.create_floatingip(
                {'floatingip': {'project_id': loadbalancer['tenant_id'],
                                'floating_network_id': fnet_id}})['floatingip']

        client.update_floatingip(fip['id'],
                                 {'floatingip':
                                  {'port_id': loadbalancer['vip_port_id']}})

        LOGGER.info("Loadbalancer external IP: %s",
                    fip['floating_ip_address'])

        return fip['floating_ip_address']

    @retry(exceptions=(StateInvalidClient,), tries=12, delay=30, backoff=0.8)
    def _add_listener(self, client):
        listener = client.create_listener({'listener':
                                           {"loadbalancer_id":
                                            self._id,
                                            "protocol": "HTTPS",
                                            "protocol_port": 6443,
                                            'admin_state_up': True,
                                            'name': '%s-listener' % self.name
                                            }})
        return listener

    @retry(exceptions=(StateInvalidClient,), tries=10, delay=3, backoff=1)
    def _add_pool(self, client, listener_id):
        pool = client.create_lbaas_pool(
            {"pool": {"lb_algorithm": "SOURCE_IP",
                      "listener_id": listener_id,
                      "loadbalancer_id": self._id,
                      "protocol": "HTTPS",
                      "name": "%s-pool" % self.name},
             })
        self.pool = pool['pool']

        return pool['pool']

    @retry(exceptions=(StateInvalidClient,), tries=10, delay=3, backoff=1,
           logger=LOGGER.debug)
    def _add_health_monitor(self, client, pool_id):
        client.create_lbaas_healthmonitor(
            {'healthmonitor':
             {"delay": 5, "timeout": 3, "max_retries": 3, "type": "TCP",
              "pool_id": pool_id,
              "name": "%s-health" % self.name}})

    @retry(exceptions=(StateInvalidClient,), tries=12, delay=3, backoff=1)
    def add_member(self, client, pool_id, ip_addr):
        """
        add listener to a loadbalancers pool.
        """
        try:
            client.create_lbaas_member(pool_id,
                                       {'member':
                                        {'subnet_id': self._subnet_id,
                                         'protocol_port': 6443,
                                         'address': ip_addr,
                                         }})
            self.members.append(ip_addr)
        except NeutronConflict:
            pass

    @retry(exceptions=(OSError, NeutronConflict), backoff=1,
           logger=LOGGER.debug)
    def _del_health_monitor(self, client, id_):  # pylint: disable=no-self-use
        """
        delete a LB health monitor
        """
        try:
            client.delete_lbaas_healthmonitor(id_)
        except NotFound:
            LOGGER.debug("Healthmonitor not found ...")
        LOGGER.info("deleted healthmonitor ...")

    @retry(exceptions=(StateInvalidClient, NeutronConflict), backoff=1,
           logger=LOGGER.debug)
    def _del_pool(self, client):
        # if pool has health monitor delete it first
        pools = list(client.list_lbaas_pools(retrieve_all=False,
                                             name="%s-pool" % self.name))
        lb_id = {'id': self._id}
        pools = pools[0]['pools']
        for pool in pools:
            if lb_id in pool['loadbalancers']:
                if pool['healthmonitor_id']:
                    self._del_health_monitor(client, pool['healthmonitor_id'])
                try:
                    client.delete_lbaas_pool(pool['id'])
                except NotFound:
                    LOGGER.debug("Pool %s not found", pool['id'])
                LOGGER.info("deleted pool ...")

    @retry(exceptions=(NeutronConflict, StateInvalidClient), backoff=1,
           logger=LOGGER.debug)
    def _del_listener(self, client):
        lb_id = {'id': self._id}
        listeners = list(client.list_listeners(retrieve_all=False,
                                               name="%s-listener" % self.name))
        listeners = listeners[0]['listeners']
        for item in listeners:
            if lb_id in item['loadbalancers']:
                try:
                    client.delete_listener(item['id'])
                except NotFound:
                    LOGGER.debug("Listener %s not found", item['id'])
                LOGGER.info("Deleted listener...")

    @retry(exceptions=(NeutronConflict, StateInvalidClient),
           tries=12, backoff=1, logger=LOGGER.debug)
    def _del_loadbalancer(self, client):
        try:
            client.delete_loadbalancer(self._id)
        except NotFound:
            LOGGER.debug("Could not find loadbalancer %s", self._id)
        LOGGER.info("Deleted loadbalancer...")

    @retry(exceptions=(StateInvalidClient,), backoff=1, tries=10)
    def _del_member(self, client, member_id, pool_id):  # pylint: disable=no-self-use
        try:
            client.delete_lbaas_member(member_id, pool_id)
        except NotFound:
            pass


class SecurityGroup:
    """
    A class to create and configure a security group in openstack
    """

    def __init__(self, neutron_client, name, subnet=None):
        self.client = neutron_client
        self.name = name
        self.subnet = subnet
        self._id = None
        self.exists = False

    def add_sec_rule(self, **kwargs):
        """
        add a security group rule
        """
        try:
            kwargs.update({'security_group_id': self._id})
            self.client.create_security_group_rule({'security_group_rule': kwargs})
        except NeutronConflict:
            kwargs.pop('security_group_id')
            print(info("Rule with %s already exists" % str(kwargs)))

    async def del_sec_rule(self, connection):
        """
        delete security rule
        """
        connection.delete_security_group_rule(self._id)

    @lru_cache()
    def get_or_create_sec_group(self, name):
        """
        Create a security group for all machines

        Args:
            neutron (neutron client)
            name (str) - the cluster name

        Return:
            a security group dict
        """
        name = "%s-sec-group" % name
        secgroup = self.client.list_security_groups(
            retrieve_all=False, **{'name': name})
        secgroup = next(secgroup)['security_groups']

        if secgroup:
            self.exists = True
            self._id = secgroup[0]['id']
            return secgroup[0]

        secgroup = self.client.create_security_group(
            {'security_group': {'name': name}})['security_group']

        self._id = secgroup['id']
        return {}

    def configure(self):
        """
        Create a future for configuring the security group ``name``

        Args:
            neutron (neutron client)
            sec_group (dict) the sec. group info dict (Munch)
        """
        if self.subnet:
            cidr = self.client.find_resource('subnet', self.subnet)['cidr']
        else:
            cidr = self.client.list_subnets()['subnets'][-1]['cidr']

        LOGGER.debug("configuring security group ...")
        # allow communication to the API server from within the cluster
        # on port 80
        self.add_sec_rule(direction='ingress', protocol='TCP',
                          port_range_max=80, port_range_min=80,
                          remote_ip_prefix=cidr)
        # Allow all incoming TCP/UDP inside the cluster range
        self.add_sec_rule(direction='ingress', protocol='UDP',
                          remote_ip_prefix=cidr)
        self.add_sec_rule(direction='ingress', protocol='TCP',
                          remote_ip_prefix=cidr)
        # allow all outgoing
        # we are behind a physical firewall anyway
        self.add_sec_rule(direction='egress', protocol='UDP')
        self.add_sec_rule(direction='egress', protocol='TCP')
        # Allow IPIP communication
        self.add_sec_rule(direction='egress', protocol=4, remote_ip_prefix=cidr)
        self.add_sec_rule(direction='ingress', protocol=4, remote_ip_prefix=cidr)
        # allow accessing the API server
        self.add_sec_rule(direction='ingress', protocol='TCP',
                          port_range_max=6443, port_range_min=6443)
        # allow node ports
        # OpenStack load balancer talks to these too
        self.add_sec_rule(direction='egress', protocol='TCP',
                          port_range_max=32767, port_range_min=30000)
        self.add_sec_rule(direction='ingress', protocol='TCP',
                          port_range_max=32767, port_range_min=30000)
        # allow SSH
        self.add_sec_rule(direction='egress', protocol='TCP',
                          port_range_max=22, port_range_min=22,
                          remote_ip_prefix=cidr)
        self.add_sec_rule(direction='ingress', protocol='TCP',
                          port_range_max=22, port_range_min=22)


def read_os_auth_variables(trim=True):
    """
    Automagically read all OS_* variables and
    yield key: value pairs which can be used for
    OS connection
    """
    env = {}
    for key, val in os.environ.items():
        if key.startswith("OS_"):
            env[key[3:].lower()] = val
    if trim:
        not_in_default_rc = ('interface', 'region_name',
                             'identity_api_version', 'endpoint_type',
                             )

        list(env.pop(i) for i in not_in_default_rc if i in env)

    return env


def get_clients():
    """
    get openstack low level clients

    This should be replaced in the future with ``openstack.connect``
    """
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
    """
    Data class to hold the configuration file for kubernetes cloud provider
    """

    def __init__(self, subnet_id=None):
        os_vars = read_os_auth_variables(trim=False)
        self.subnet_id = subnet_id
        self.username = os_vars['username']
        self.password = os_vars['password']
        self.auth_url = os_vars['auth_url']
        self.__dict__.update(os_vars)
        # pylint does not catch the additions of member we add above
        self.tenant_id = self.project_id  # pylint: disable=no-member
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
        """ % (self.username,
               self.password,
               self.auth_url,  # pylint: disable=no-member
               self.tenant_id,
               self.user_domain_name,  # pylint: disable=no-member
               self.region_name)).lstrip()  # pylint: disable=no-member
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


def distribute_host_zones(hosts, zones):
    """
    this divides the lists of hosts into zones
    >>> hosts
    >>> ['host1', 'host2', 'host3', 'host4', 'host5']
    >>> zones
    >>> ['A', 'B']
    >>> list(zip([hosts[i:i + n] for i in range(0, len(hosts), n)], zones)) # noqa
    >>> [(['host1', 'host2', 'host3'], 'A'), (['host4', 'host5'], 'B')]  # noqa
    """

    if len(zones) == len(hosts):
        return list(zip(hosts, zones))

    hosts = [hosts[start::len(zones)] for start in range(len(zones))]
    return list(zip(hosts, zones))


class OSClusterInfo:  # pylint: disable=too-many-instance-attributes
    """
    collect various information on the cluster

    """
    def __init__(self, nova_client, neutron_client,
                 cinder_client,
                 config):

        self.keypair = nova_client.keypairs.get(config['keypair'])
        self.image = nova_client.glance.find_image(config['image'])
        self.node_flavor = nova_client.flavors.find(name=config['node_flavor'])
        self.master_flavor = nova_client.flavors.find(
            name=config['master_flavor'])

        secgroup = SecurityGroup(neutron_client, config['cluster-name'],
                                 subnet=config.get('subnet'))

        secgroup.get_or_create_sec_group(config['cluster-name'])
        self.secgroup = secgroup
        self.secgroups = [secgroup._id]

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
        self._cinderclient = cinder_client

    @lru_cache()
    def _get_or_create(self, hostname, zone, role):
        """
        Find if a instance exists Openstack.

        If instance is found return Instance instance with the info.
        If not found create a NIC and assign it to an Instance instance.
        """
        volume_config = {'image': self.image, 'class': self.storage_class}
        try:
            _server = self._novaclient.servers.find(name=hostname)
            inst = Instance(self._cinderclient,
                            self._novaclient,
                            _server.name,
                            self.net,
                            zone,
                            role,
                            volume_config)
            inst._ports.append(_server.interface_list()[0])
            inst.exists = True
        except NovaNotFound:
            inst = Instance(self._cinderclient,
                            self._novaclient,
                            hostname,
                            self.net,
                            zone,
                            role,
                            volume_config)
            inst.attach_port(self._neutronclient,
                             self.net['id'],
                             self.secgroups)
        return inst

    @property
    def nodes_names(self):
        """get the host names of all worker nodes"""
        return host_names("node", self.n_nodes, self.name)

    @property
    def management_names(self):
        """get the host names of all control plane nodes"""
        return host_names("master", self.n_masters, self.name)

    def distribute_management(self):
        """
        distribute control plane nodes in the different availability zones
        """
        mz = list(distribute_host_zones(self.management_names, self.azones))
        for hosts, zone in mz:
            for host in hosts:
                yield self._get_or_create(host, zone, 'master')

    def distribute_nodes(self):
        """
        distribute worker nodes in the different availability zones
        """
        hz = list(distribute_host_zones(self.nodes_names, self.azones))
        for hosts, zone in hz:
            for host in hosts:
                yield self._get_or_create(host, zone, 'node')
