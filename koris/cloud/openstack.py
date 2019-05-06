"""
functions and classes to interact with openstack
"""
# pylint: disable=too-many-lines
import asyncio
import base64
import copy
import os
import sys
import textwrap

from functools import lru_cache

from netaddr import IPNetwork, valid_ipv4, valid_ipv6
from novaclient import client as nvclient
from novaclient.exceptions import (NotFound as NovaNotFound, NoUniqueMatch)  # noqa
from cinderclient import client as cclient
from neutronclient.v2_0 import client as ntclient

from neutronclient.common.exceptions import (Conflict as NeutronConflict,
                                             StateInvalidClient, NotFound,
                                             BadRequest)

from openstack.exceptions import ConflictException as OSConflict
from openstack.exceptions import ResourceNotFound as OSNotFound

from keystoneauth1 import identity
from keystoneauth1 import session

from koris.cloud import OpenStackAPI
from koris.util.util import (host_names, retry)
from koris.util.logger import Logger
from koris import MASTER_LISTENER_NAME, MASTER_POOL_NAME


LOGGER = Logger(__name__)


# OpenStack clients. Initialized at time of calling get_clients. You should not
# use these directly bur rather call get_clients to ensure those variables
# get initialized correctly.
NOVA, NEUTRON, CINDER = None, None, None


# pylint: disable=redefined-outer-name, global-statement
def get_clients():
    """
    get openstack low level clients

    This should be replaced in the future with ``openstack.connect``
    """
    global NOVA, NEUTRON, CINDER
    if(not NOVA or not NEUTRON or not CINDER):
        # at least one client has not already been initialized
        try:
            auth = identity.Password(**read_os_auth_variables())
            sess = session.Session(auth=auth)
            NOVA = nvclient.Client('2.1', session=sess)
            NEUTRON = ntclient.Client(session=sess)
            CINDER = cclient.Client('3.0', session=sess)

        except TypeError:
            LOGGER.error("Did you source your OS rc file in v3?")
            LOGGER.error("If your file has the key OS_ENDPOINT_TYPE it's the"
                         " wrong one!")
            sys.exit(1)
        except KeyError:
            LOGGER.error("Did you source your OS rc file?")
            sys.exit(1)
    return NOVA, NEUTRON, CINDER


if getattr(sys, 'frozen', False):  # pragma: nocoverage
    def monkey_patch():
        """monkey patch get available versions, because the original
        code uses __file__ which is not available in frozen build"""
        return ['2', '1']
    nvclient.api_versions.get_available_major_versions = monkey_patch

    def monkey_patch_cider():
        """the same spiel for cinder"""
        return ['3']
    cclient.api_versions.get_available_major_versions = monkey_patch_cider  # noqa


def get_connection():
    """Establishes an OpenStack connection.

    This function will exit with error code 1 in case a connection could not be
    established.

    Returns:
        conn (OpenStackAPI.Connection): an OpenStack Connection Object.
    """

    try:
        conn = OpenStackAPI.connect()
    except OpenStackAPI.exceptions.ConfigException as exc:
        LOGGER.error("unable to establish OpenStack Cloud connection:")
        LOGGER.error("%s - have you sourced your OpenStack RC file?", exc)
        sys.exit(1)

    if conn is None or conn.session is None:
        LOGGER.error("unable to establish OpenStack Cloud connection")
        sys.exit(1)

    return conn


def delete_instance(name, conn, ignore_not_found=True):
    """Removes a server from OpenStack.

    This will also remove Volumes and Network ports.

    Args:
        name (str): Name of the Server to delete.
        conn: An OpenStack Connection object.
        ignore_not_found (bool): If set to False, raises
            InstanceNotFound if the instance doesn't exist.
    """

    srv = conn.compute.find_server(name)
    if not srv or srv is None:
        msg = f"Instance '{name}' doesn't exist, skipping deletion"
        if ignore_not_found:
            LOGGER.info(msg)
            return

        raise InstanceNotFound(msg)

    # Deleting the instance and volumes
    conn.compute.delete_server(srv)

    # Deleting attached network ports
    ports = list(conn.network.ports(device_id=srv.id))
    for port in ports:
        conn.network.delete_port(port)

    LOGGER.success("OpenStack instance '%s' has been deleted successfully",
                   name)


class BuilderError(Exception):
    """Raise a custom error if the build fails"""


class InstanceExists(Exception):
    """raise a custom error if the machine exists"""


class InstanceNotFound(Exception):
    """Raises a custom error if machine doesn't exist."""


class Instance:  # pylint: disable=too-many-arguments
    """
    Create an Openstack Server with an attached volume
    """

    def __init__(self, cinder, nova, name, network, zone, role,
                 volume_config, flavor):
        self.cinder = cinder
        self.nova = nova
        self.name = name
        self.network = network
        self.zone = zone
        self.flavor = flavor
        self.volume_config = volume_config
        self.role = role
        self.ports = []
        self._ip_address = None
        self.exists = False

    @property
    def nics(self):
        """return all network interfaces attached to the instance"""
        return [{'net-id': self.network['id'],
                 'port-id': self.ports[0]['port']['id']}]

    @property
    def ip_address(self):
        """return the IP address of the first NIC"""
        try:
            return self.ports[0]['port']['fixed_ips'][0]['ip_address']
        except TypeError:
            return self.ports[0].fixed_ips[0]['ip_address']
        except IndexError:
            raise AttributeError("Instance has no ports attached")

    def attach_port(self, netclient, net, secgroups):
        """associate a network port with an instance"""
        port = netclient.create_port({"port": {"admin_state_up": True,
                                               "network_id": net,
                                               "security_groups": secgroups}})
        self.ports.append(port)

    async def _create_volume(self):  # pragma: no coverage
        bdm_v2 = {
            "boot_index": 0,
            "source_type": "volume",
            "volume_size": str(self.volume_config.get('size', 25)),
            "destination_type": "volume",
            "delete_on_termination": True}

        vol = self.cinder.volumes.create(self.volume_config.get('size', 25),
                                         name=self.name,
                                         imageRef=self.volume_config.get('image').id,
                                         availability_zone=self.zone,
                                         volume_type=self.volume_config.get('class'))

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
            LOGGER.error("Something weired happend, I so I didn't create %s" %
                         self.name)
            LOGGER.info("Removing cluster ...")
            LOGGER.info(f"Exception: {err}")
            raise BuilderError(str(err))

        inst_status = instance.status
        LOGGER.debug("Waiting 5 seconds for machine to be launched ... ")
        await asyncio.sleep(5)

        while inst_status == 'BUILD':
            LOGGER.debug(
                "Instance: %s is in in %s state, sleeping for 5 more seconds",
                instance.name, inst_status)
            await asyncio.sleep(5)
            instance = self.nova.servers.get(instance.id)
            inst_status = instance.status

        LOGGER.debug(f"Instance '{instance.name} is in state: {inst_status}")

        self._ip_address = instance.interface_list()[0].fixed_ips[0]['ip_address']
        LOGGER.success(
            "Instance '%s' booted successfully. IP: %s, Status : %s",
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
            LOGGER.success("Instance '%s' deleted successfully", server.name)
        except NovaNotFound:
            pass


class LoadBalancer:
    """A class to create a LoadBalancer in OpenStack.

    Openstack allows one to create a loadbalancer and configure it later.
    Thus we create a LoadBalancer, so we have it's IP. The IP
    of the LoadBalancer, is then stored in the SSL certificates.
    During the boot of the machines, we configure the LoadBalancer.
    """

    def __init__(self, config, conn):
        self.floatingip = config.get('loadbalancer', {}).get('floatingip', '')
        self.config = config
        if not self.floatingip:
            LOGGER.warning("No floating IP, I hope it's OK")
        self.name = "%s-lb" % config['cluster-name']

        try:
            self.subnet_name = config.get('private_net')['subnet'].get('name', self.name)
        except (KeyError, TypeError):
            self.subnet_name = None

        # these attributes are set after creation
        self._id = None
        self._subnet_id = None
        self._data = None
        self._existing_floating_ip = None
        self.conn = conn

    @property
    def master_listener(self):
        """Returns the listener of name MASTER_LISTENER_NAME, including additional info.

        Returns:
            A dict containing all necessary information of the master listener::

                {
                    'name': '<listener.name:str>',
                    'id': '<listener.id:str>',
                    'pool': {
                        'name': '<pool.name:str>',
                        'id': '<pool.id:str>',
                            'members': [
                                {
                                    'id': '<pool.members[i].id:str>',
                                    'name': '<member.name:str>',
                                    'address': '<member.address:str>',
                                },
                                {...}
                            ]
                        },
                    }
                }
        """

        listener = self._get_master_listener()
        if not listener:
            return None

        if listener.name != MASTER_LISTENER_NAME:
            LOGGER.error("Listener '%s' (%s) should be named (%s)",
                         listener.name, listener.id, MASTER_LISTENER_NAME)
            return None

        pool = self._pool_info(listener.default_pool_id)

        out = {}
        out['name'] = listener.name
        out['id'] = listener.id
        out['pool'] = pool

        return out

    def _get_master_listener(self):  # pylint: disable=too-many-return-statements
        """Returns the Listener with name MASTER_LISTENER_NAME associated to the LB."""

        # LB isn't configured yet
        if not self._id or not self._data:
            LOGGER.error("LoadBalancer not configured yet")
            return None

        # Get our LB from OpenStack
        lb = self.conn.load_balancer.find_load_balancer(self._id)
        if not lb:
            LOGGER.error("Unable to find LoadBalancer '%s' (%s)", self.name, self._id)
            return None

        # Check if LB has listeners
        if not lb.listeners:
            LOGGER.error("LoadBalancer '%s' (%s) has no listeners", self.name, self._id)
            return None

        # Iterate over Listeners associated with LB...
        master_listeners = []
        for li in lb.listeners:
            # Check if single Listener has name MASTER_LISTENER_NAME
            try:
                listener = self.conn.load_balancer.find_listener(li['id'])
            except (TypeError, KeyError) as exc:
                LOGGER.error("Unable to access LoadBalancer.listeners: %s", exc)
                return None

            # Not this one, check next
            if not listener:
                continue

            # This one is good, append to list
            if listener.name == MASTER_LISTENER_NAME:
                master_listeners.append(listener)

        if not master_listeners:
            LOGGER.error("Unable to find Listener with name '%s'", MASTER_LISTENER_NAME)
            return None

        if len(master_listeners) > 1:
            LOGGER.error("Found more than one Listener found with name '%s'",
                         MASTER_LISTENER_NAME)
            return None

        return master_listeners[0]

    def _pool_info(self, pool_id):
        """A list with Pool Information of a Listener.

        Args:
            listener (:class:`OpenStackAPI.network.Listener`): An OpenStack Listener
                Object

        Returns:
            A dict which is of the following structure:
                {
                    'name': '<pool.name:str>',
                    'id': '<pool.id:str>',
                        'members': [
                            {
                                'id': '<pool.members[i].id:str>',
                                'name': '<member.name:str>',
                                'address': '<member.address:str>',
                            },
                            {...}
                        ]
                    },
                }
        """

        pool = self.conn.load_balancer.find_pool(pool_id)
        if not pool:
            LOGGER.debug("Unable to find pool '%s'", pool_id)
            return None

        # Get information about every member in the pool
        members = []
        for mem in pool.members:
            mem_id = mem['id']

            member = self.conn.load_balancer.find_member(mem_id, pool)
            if not member:
                LOGGER.debug("Unable to find member '%s' in pool '%s' (%s)",
                             mem_id, pool.name, pool_id)
                continue

            members.append({
                'id': mem_id,
                'name': member.name,
                'address': member.address
            })

        pool = {
            'name': pool.name,
            'id': pool.id,
            'members': members
        }

        return pool

    async def configure(self, master_ips):
        """Configure a load balancer created in earlier step

        Args:
            master_ips (list): A list of the master IP addresses
        """

        # If not present, add listener
        if not self._data.listeners:
            listener = self.add_listener(name=MASTER_LISTENER_NAME)
            listener_id = listener.id
        else:
            LOGGER.debug("Reusing listener %s", self._data.listeners[0].id)
            listener_id = self._data.listeners[0].id

        if not self._data.pools:
            pool = self.add_pool(listener_id, name=MASTER_POOL_NAME)
        else:
            LOGGER.debug("Reusing pool, removing all members ...")
            # (aknipping) This should be handled differently. If there are multiple
            # pools present, we want to specify which it should be added too. Maybe with a
            # default pool name that is independent of the cluster name?
            pool = self.conn.network.find_pool(self._data.pools[0]['id'])
            for member_id in [list(x.values())[0] for x in pool.members]:
                self.del_member(member_id, pool.id)

        for member in master_ips:
            LOGGER.debug("Adding member %s ...", member)
            self.add_member(pool.id, member)
        if pool.get('healthmonitor_id'):
            LOGGER.debug("Reusing existing health monitor")
        else:
            self.add_health_monitor(pool.id)

    def get(self):
        """Retrieve LoadBalancer information"""

        lb = self.conn.load_balancer.find_load_balancer(self.name)
        if lb:
            self._id = lb.id
            self._subnet_id = lb.vip_subnet_id
            self._data = lb

        return lb

    def get_or_create(self):
        """Retrieve or create a LoadBalancer"""

        lb = self.get()

        if not lb or 'DELETE' in lb['provisioning_status']:
            lb, fip_addr = self.create()
        else:
            LOGGER.debug("Reusing existing LoadBalancer ...")
            self._existing_floating_ip = None
            fip_addr = self._floating_ip_address(lb)
            LOGGER.success("Loadbalancer IP: %s", fip_addr)
            self._id = lb.id
            self._subnet_id = lb.vip_subnet_id
            self._data = lb

        return lb, fip_addr

    @property
    def ip_address(self):
        """Return the LoadBalancer's IP or Floating IP address"""

        if not self._data:
            self.get()

        if self._data.vip_address:
            return self._data.vip_address

        if self._existing_floating_ip:
            return self._existing_floating_ip

        try:
            floatingips = list(self.conn.network.ips(port_id=self._data.vip_port_id))
        except (AttributeError, TypeError):
            pass

        if floatingips:
            self._existing_floating_ip = floatingips[0].floating_ip_address

            return self._existing_floating_ip

        return None

    def _floating_ip_address(self, lb):
        floatingips = list(self.conn.network.ips(port_id=lb.vip_port_id))
        if floatingips:
            self._existing_floating_ip = floatingips[0].floating_ip_address
            fip_addr = self._existing_floating_ip
        else:
            if isinstance(self.floatingip, str):
                fip_addr = self.associate_floating_ip(lb)
            else:
                fip_addr = None
        return fip_addr

    def create(self):
        """Provision a minimally configured LoadBalancer in OpenStack

        Return:
            tuple (dict, str) - the dict is the load balancer information, if
            a floating IP was associated it is returned as a string. Else it's
            None.
        """
        # see examle of how to create an LB
        # https://developer.openstack.org/api-ref/load-balancer/v2/index.html#id6

        if self.subnet_name:
            subnet_id = self.conn.get_subnet(self.subnet_name).id
        else:
            # match created subnet id with the corresponding one in subnets
            network = OSNetwork(self.config, self.conn).get_or_create()
            subnets = list(self.conn.network.subnets(network_id=network.id))
            subnet_id = subnets[0].id

        lb = self.conn.load_balancer.create_load_balancer(
            vip_subnet_id=subnet_id,
            name=f"{self.name}"
        )

        self._id = lb.id
        self._subnet_id = subnet_id
        self._data = lb

        LOGGER.success("LoadBalancer '%s' (%s) created successfully",
                       self.name, self._id)

        fip_addr = None

        # Only associate floatingip if it's set to a value in config
        # (aknipping) for now, setting it to 'true' will not do anything
        if isinstance(self.floatingip, str):
            fip_addr = self.associate_floating_ip(lb)
        return lb, fip_addr

    @retry(exceptions=(NeutronConflict, NotFound, BadRequest), backoff=1,
           tries=10, logger=LOGGER.debug)
    def delete(self):
        """Delete the cluster API loadbalancer

        Deletion order of LoadBalancer (done via --cascade):
            - remove pool (LB is pending up date)
            - if healthmonitor in pool, delete it first
            - remove listener (LB is pending update)
            - remove LB (LB is pending delete)
        """

        # Check if LB is assigned
        lb = self._data
        if not lb:
            # Find LB in OpenStack
            lb = self.get()

        if not lb or 'DELETE' in lb.operating_status:
            LOGGER.warning("LoadBalancer %s was not found", self.name)
        else:
            LOGGER.debug("Deleting LoadBalancer %s ...", self.name)
            self._del_loadbalancer()

    def associate_floating_ip(self, loadbalancer):
        """Associates a Floating IP with the LoadBalancer"""

        valid_ip = valid_ipv4(self.floatingip) or valid_ipv6(self.floatingip)
        if not valid_ip:
            LOGGER.error("'%s' is not a valid IP address", self.floatingip)
            sys.exit(1)
        if self._existing_floating_ip == self.floatingip:
            return self._existing_floating_ip

        # Check if Floating IP exists in OpenStack
        fip = self.conn.network.find_ip(self.floatingip)
        if not fip:
            LOGGER.error("Floating IP %s doesn't exist, please create it first",
                         self.floatingip)
            sys.exit(1)

        # Assign IP to LB
        fip = self.conn.network.update_ip(fip, port_id=loadbalancer.vip_port_id)

        LOGGER.success("Loadbalancer external IP: %s",
                       fip.floating_ip_address)

        return fip.floating_ip_address

    @retry(exceptions=(StateInvalidClient, OSConflict), tries=20, delay=30,
           backoff=1, logger=LOGGER.debug)
    def add_listener(self, name=None, protocol="HTTPS",
                     protocol_port=6443):
        """Adds a custom listener to the LoadBalancer"""

        if name is None:
            name = self.name

        listener = self.conn.network.create_listener(load_balancer_id=self._id,
                                                     protocol=protocol,
                                                     protocol_port=protocol_port,
                                                     is_admin_state_up=True,
                                                     name=name)

        if not listener:
            LOGGER.error("Unable to add listener '%s' to LoadBalancer %s",
                         name, self._id)
            return None

        LOGGER.debug("Added %s listener '%s' (%s) on port %i to LB %s",
                     protocol, name, listener.id, protocol_port, self._id)
        return listener

    @retry(exceptions=(StateInvalidClient, OSConflict), tries=30, delay=5, backoff=1,
           logger=LOGGER.debug)
    def add_pool(self, listener_id, lb_algorithm="SOURCE_IP", protocol="HTTPS",
                 name=None):
        """Adds a pool to a listener"""

        if name is None:
            name = f"{self.name}-pool"

        pool = self.conn.network.create_pool(listener_id=listener_id,
                                             load_balancer_id=self._id,
                                             protocol=protocol,
                                             lb_algorithm=lb_algorithm,
                                             name=name)

        if not pool:
            LOGGER.error("Unable to add pool '%s' to listener %s", name, listener_id)
            return None

        LOGGER.debug("Added %s pool '%s' (%s) with %s to listener %s",
                     protocol, name, pool.id, lb_algorithm, listener_id)
        return pool

    @retry(exceptions=(StateInvalidClient, OSConflict), tries=24, delay=10,
           backoff=0.8, logger=LOGGER.debug)
    def add_health_monitor(self, pool_id, name=None):
        """Adds a Healthmonitor to a Pool"""

        if name is None:
            name = f"{self.name}-health"

        hm = self.conn.network.create_health_monitor(
            delay=5,
            timeout=3,
            max_retries=4,
            type="TCP",
            pool_id=pool_id,
            name=name)

        if not hm:
            LOGGER.error("Unable to add health monitor '%s' to pool %s", name, pool_id)
            return None

        LOGGER.debug("Added health monitor '%s' (%s) to pool %s", name, hm.id,
                     pool_id)
        return hm

    @retry(exceptions=(StateInvalidClient, OSConflict, BadRequest), tries=24,
           delay=5, backoff=1, logger=LOGGER.debug)
    def add_member(self, pool_id, ip_addr, protocol_port=6443):
        """Adds a Listener to a Pool."""

        member = self.conn.network.create_pool_member(
            pool=pool_id,
            subnet_id=self._subnet_id,
            protocol_port=protocol_port,
            address=ip_addr)

        if not member:
            LOGGER.error("Unable to add member '%s' to pool %s", ip_addr, pool_id)
            return None

        LOGGER.debug("Added member '%s' (%s) to pool %s on port %i", ip_addr,
                     member.id, pool_id, protocol_port)

        return member

    @retry(exceptions=(OSConflict, StateInvalidClient, BadRequest),
           tries=25, delay=15, backoff=0.8, logger=LOGGER.debug)
    def _del_loadbalancer(self):
        try:
            self.conn.load_balancer.delete_load_balancer(
                self._id,
                ignore_missing=False,
                cascade=True)
            LOGGER.success("LoadBalancer '%s' (%s) deleted successfully",
                           self.name, self._id)
        except OSNotFound:
            LOGGER.debug("Could not find  LoadBalancer %s", self._id)

    @retry(exceptions=(StateInvalidClient, OSConflict), backoff=1, tries=5, delay=5,
           logger=LOGGER.debug)
    def del_member(self, member_id, pool_id):  # pylint: disable=no-self-use
        """Deletes a member from the LoadBalancer.

        Args:
            member_id (str): The ID of the member to be deleted.
            pool_id (str): The ID of the pool where the member is located.
        """

        try:
            self.conn.network.delete_pool_member(member_id, pool_id, ignore_missing=False)
            LOGGER.debug("Deleted member %s from pool %s", member_id, pool_id)
        except OSNotFound:
            LOGGER.debug("Member %s not found in pool %s", member_id, pool_id)


class SecurityGroup:
    """A class to create and configure a security group in OpenStack.

    This class behaves differently as the OSNetwork, OSSubnet and OSRouter
    classes as we need to additional functions on it, such as ``configure``.

    Args:
        name (str): The name of the Security Group
        conn: An OpenStack Connection object
        subnet: An OpenStack Subnet object
    """

    def __init__(self, name, conn, subnet):
        self.name = f"{name}-sec-group"
        self.conn = conn
        self.subnet = subnet
        self.id = None

    def add_sec_rule(self, **kwargs):
        """Adds a security group rule."""
        try:
            kwargs.update({'security_group_id': self.id})
            LOGGER.debug("Adding rule %s ...", str(kwargs))
            self.conn.network.create_security_group_rule(**kwargs)
        except OSConflict:
            kwargs.pop('security_group_id')
            LOGGER.debug("Rule %s already exists" % str(kwargs))

    async def del_sec_rule(self):
        """Deletes a security rule."""
        self.conn.delete_security_group_rule(self.id)

    @property
    def exists(self):
        """Checks if this SecurityGroup has been created in OpenStack."""

        return self.get() is not None

    def get(self):
        """Retrieves the SecurityGroup from OpenStack.

        If it exists, will also set the ``id`` attribute of the class.
        """

        sg = self.conn.network.find_security_group(self.name)
        if sg:
            self.id = sg.id

        return sg

    @lru_cache()
    def get_or_create(self):
        """Retrieves or creates a security group for all machines.

        Return:
            An OpenStack Security Group Object.
        """

        secgroup = self.get()
        if secgroup:
            LOGGER.info(f"Using SecurityGroup [{secgroup.name}] ...")
        else:
            LOGGER.info(f"Creating SecurityGroup [{self.name}] ...")
            secgroup = self.conn.network.create_security_group(name=self.name)

        self.id = secgroup.id
        LOGGER.debug("Created SecurityGroup: %s", secgroup)
        return secgroup

    def configure(self):
        """Configures the SecurityGroup for cluster usage."""
        cidr = self.subnet['cidr']

        LOGGER.debug("Configuring Security Group ...")
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


class OSNetwork:  # pylint: disable=too-few-public-methods
    """Manages a Network on OpenStack.

    The name will be taken from the config or set to
    ``cluster-name``-net.

    Args:
        config (dict): A dictionary containing the koris config parameters.
        conn: An OpenStack connection object.
    """
    def __init__(self, config, conn):
        self.config = config
        self.conn = conn

        if 'private_net' not in self.config:
            self.name = "%s-net" % self.config['cluster-name']
        else:
            self.name = self.config.get('private_net')['name']

    def get(self):
        """Retrieves a Network from OpenStack.

        Returns:
            An OpenStack Network object, or None.
        """

        return self.conn.get_network(self.name)

    def get_or_create(self):
        """Retrieves or creates a Network.

        Returns:
            An OpenStack Network object.
        """
        network = self.get()
        if not network:
            LOGGER.info("Creating network [%s] ... " % self.name)
            network = self.conn.create_network(name=self.name,
                                               admin_state_up=True)

        if 'private_net' in self.config:
            self.config['private_net'].update(network)
        else:
            self.config['private_net'] = network

        LOGGER.debug("Network: %s", network)
        return network

    # pylint: disable=inconsistent-return-statements
    @staticmethod
    def find_external_network(conn, default="ext02", fallback="ext01"):
        """Finds and returns an external network in OpenStack.

        This function will look for all external networks, then try to find the
        one with name passed as the "default" parameter. In case this can't be
        found, it will try to return the external network with the "fallback"
        parameter. In case this can't be found, it will return the first
        external network it finds.

        Args:
            conn (:class:`OpenStackAPI.connection.connection`): An OpenStack Connection.
            default (str): The default external network to use.
            fallback (str): The fallback external network to use in case the default
                is not found.

        Returns:
            An :class:`OpenStackAPI.network.v2.network` object or None if no external
                network can be found.
        """

        # Retrieve all external networks as list

        # import pdb; pdb.set_trace()
        ext_networks = list(conn.network.networks(is_router_external=True))

        for net_name in [default, fallback]:
            nets = [x for x in ext_networks if x.name == net_name]
            if nets:
                return nets[0]


class OSSubnet:  # pylint: disable=too-few-public-methods
    """Manages a Subnet on OpenStack.

    Args:
        network_id (str): The UUID of the Network to create the Subnet in.
        config (dict): A dictionary containing the koris config parameters.
        conn: An OpenStack Connection object.
    """
    def __init__(self, network_id, config, conn):
        self.net_id = network_id
        self.config = config
        self.conn = conn
        self.name = self._name()

    def _name(self):
        """Sets the name for Subnet.

        This value will either be taken from the config or set as
        ``cluster-name``-subnet.

        Returns:
            The name as string.
        """
        subnet_name = None
        for key in ['subnet', 'subnets']:
            if key in self.config.get('private_net', ''):
                try:
                    subnet_name = self.config.get('private_net')['subnet']['name']
                except KeyError:
                    continue

        if not subnet_name:
            subnet_name = "%s-subnet" % self.config['cluster-name']

        return subnet_name

    def get(self):
        """Retrieves a Subnet from OpenStack.

        Returns:
            An OpenStack Subnetwork Object or None.
        """

        return self.conn.network.find_subnet(self.name)

    def get_or_create(self):
        """Retrieves or creates a Subnet on OpenStack.

        If a new Subnetwork is created, additional information will be saved
        in the config.

        Returns:
            An OpenStack Subnetwork Object.
        """

        out = self.get()
        if out:
            LOGGER.debug("Subnet: %s", out)
            return out

        LOGGER.info("Creating Subnet [%s] ..." % self.name)
        subnet = {}
        if 'subnet' in self.config.get('private_net', {}):
            subnet['cidr'] = self.config.get('private_net').get('subnet')['cidr']
        else:
            subnet['cidr'] = '192.168.0.0/16'

        subnet['ip_version'] = 4
        subnet['network_id'] = self.net_id
        subnet['name'] = self.name

        out = self.conn.network.create_subnet(
            name=subnet['name'],
            ip_version=subnet['ip_version'],
            network_id=subnet['network_id'],
            cidr=subnet['cidr']
        )

        self.config['private_net']['subnet'] = subnet
        LOGGER.debug("Subnet: %s", out)
        return out


class OSRouter:  # pylint: disable=too-few-public-methods
    """A class managing a Router on OpenStack.

    Args:
        network_id (str): The UUID of the OpenStack Network.
        subnet: An OpenStack Subnetwork Object.
        config (dcit): A dictionary containing koris config parameters.
        conn: An OpenStack Connection Object.
    """
    def __init__(self, network_id, subnet, config, conn):
        self.net_id = network_id
        self.subnet = subnet
        self.config = config
        self.conn = conn
        self.name = self._name()
        self.ext_net = self._get_ext_net()

    def _name(self):
        """Returns the name of the default Router."""

        if 'router' in self.config.get('private_net',
                                       {}).get('subnet', {}):
            router_name = self.config.get(
                'private_net')['subnet']['router']['name']
        else:
            router_name = "%s-rt" % self.config['cluster-name']

        return router_name

    def _get_ext_net(self):
        """Sets the external network on the Router.

        Raises:
            RuntimeError if external network doesn't exist.

        Returns:
            The external network as OpenStack Network Object.
        """

        ext_net = OSNetwork.find_external_network(self.conn)
        if ext_net is None:
            LOGGER.error("No external network found")
            raise RuntimeError("no external network found")

        return ext_net

    def get(self):
        """Retrieves a Router by the default name from OpenStack."""

        return self.conn.network.find_router(self.name)

    def get_or_create(self):
        """Retrieves or creates a Router on OpenStack.

        Function will create the router, create a new port and add it as an
        interface to the router, then adding and external gateway.

        Returns:
            An OpenStack Router object.
        """

        router = self.get()
        if not router:
            LOGGER.info(f"Creating Router [{self.name}] ...")

            LOGGER.debug("Setting up Router ...")
            router = self.conn.network.create_router(name=self.name,
                                                     admin_state_up=True)
            LOGGER.debug(router)

            LOGGER.debug("Creating new Port for Router ...")
            router_ip = IPNetwork(self.subnet.get('cidr', "192.168.0.0/16"))[1]
            fixed_ips = [{
                "ip_address": str(router_ip),
                "subnet_id": self.subnet['id']
            }]
            port = self.conn.network.create_port(name=f"{self.name}-port",
                                                 network_id=self.net_id,
                                                 admin_state_up=True,
                                                 fixed_ips=fixed_ips)
            LOGGER.debug("Created Port: %s", port)

            LOGGER.debug("Attaching Port to Router as interface ...")
            cmd = self.conn.network.add_interface_to_router(
                router=router,
                subnet_id=self.subnet['id'],
                port_id=port.id
            )
            LOGGER.debug("Updated Router: %s", cmd)

            LOGGER.debug("Adding external Gateway to Router ...")
            cmd = self.conn.network.update_router(
                router,
                external_gateway_info={"network_id": self.ext_net.id}
            )
            LOGGER.debug("Router: %s", cmd)

        return router


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
        username="%s"
        password="%s"
        auth-url="%s"
        tenant-id="%s"
        domain-name="%s"
        region="%s"
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
        hosts = [(i, ) for i in hosts]
        return list(zip(hosts, zones))

    hosts = [hosts[start::len(zones)] for start in range(len(zones))]
    return list(zip(hosts, zones))


class OSClusterInfo:  # pylint: disable=too-many-instance-attributes
    """Class containing various information of the cluster.

    This tries to retrieve the Network, Subnetwork, Router and Security Group
    from OpenStack. If any of those can't be retrieved, the attributes are
    set to ``None``. The function :meth:`.setup_networking` can initialize
    all resources.

    It is the responsibility of the client to check if the resources are
    available and set them up, if necessary.

    Args:
        nova_client: An OpenStack NOVA Client
        neutron_client: An OpenStack NEUTRON Client
        cinder_client: An OpenStack CINDER Client
        config (dict): A dictionary containing koris config parameters.
        conn: An OpenStack Connection Object.
    """
    def __init__(self, nova_client, neutron_client,
                 cinder_client,
                 config,
                 conn):

        self.conn = conn
        self.keypair = nova_client.keypairs.get(config['keypair'])
        self.node_flavor = nova_client.flavors.find(name=config['node_flavor'])
        self.master_flavor = nova_client.flavors.find(
            name=config['master_flavor'])

        try:
            self.net = OSNetwork(config, self.conn).get()
            self.subnet = OSSubnet(self.net['id'],
                                   config,
                                   self.conn).get()
            self.router = OSRouter(self.net['id'],
                                   self.subnet,
                                   config,
                                   self.conn).get()
            self.subnet_id = self.subnet['id']
            self.secgroup = SecurityGroup(config['cluster-name'],
                                          self.conn,
                                          subnet=self.subnet)
            sg = self.secgroup.get()
            self.secgroups = [sg.id]
        except (TypeError, KeyError, AttributeError):
            self.net = None
            self.subnet = None
            self.router = None
            self.subnet_id = None
            self.secgroup = None
            self.secgroups = []

        self.name = config['cluster-name']
        self.n_nodes = config['n-nodes']
        self.n_masters = config['n-masters']
        self.azones = config['availibility-zones']
        self.storage_class = config['storage_class']
        self._image_name = config['image']
        self._nova = nova_client
        self._neutron = neutron_client
        self._cinder = cinder_client
        self.config = config

    def setup_networking(self, config=None):
        """Creates Network, Subnet, Router and Security Group if necessary.

        This function is ephemeral, as it checks if the resources are existing,
        before creating them.

        Args:
            config (dict): A dictionary containing the koris config parameters.
        """

        if not config:
            config = self.config

        if not self.net:
            self.net = OSNetwork(config, self.conn).get_or_create()
        else:
            LOGGER.debug(f"Using existing Network [{self.net.name}] ...")

        if not self.subnet:
            self.subnet = OSSubnet(self.net['id'],
                                   config,
                                   self.conn).get_or_create()
        else:
            LOGGER.debug(f"Using existing Subnet [{self.subnet.name}] ...")

        if not self.router:
            self.router = OSRouter(self.net['id'],
                                   self.subnet,
                                   config,
                                   self.conn).get_or_create()
        else:
            LOGGER.debug(f"Using existing Router [{self.router.name}] ...")

        if not self.secgroup:
            self.secgroup = SecurityGroup(name=config['cluster-name'],
                                          conn=self.conn,
                                          subnet=self.subnet)

        if not self.secgroup.exists:
            sg = self.secgroup.get_or_create()
        else:
            LOGGER.debug(f"Using existing SecurityGroup [{self.secgroup.name}] ...")

        if not self.secgroups:
            sg = self.secgroup.get_or_create()
            self.secgroups = [sg.id]

    @property
    def image(self):
        """find the koris image in OpenStackAPI"""
        try:
            return self._nova.glance.find_image(self._image_name)
        except NoUniqueMatch:
            return self._nova.glance.find_image(
                [l.id for l in self.conn.list_images() if l.name == self._image_name][0])

    def _get(self, hostname, zone, role):
        """Retrieves an Instance from OpenStack."""

        volume_config = {'image': self.image, 'class': self.storage_class}
        inst = None
        try:
            _server = self._nova.servers.find(name=hostname)
            LOGGER.debug("Found instance %s", hostname)
            inst = Instance(self._cinder,
                            self._nova,
                            _server.name,
                            self.net,
                            zone,
                            role,
                            volume_config,
                            _server.flavor)
            try:
                inst.ports.append(_server.interface_list()[0])
            except IndexError:
                LOGGER.warning("No network found for %s", hostname)

            inst.exists = True
        except NovaNotFound:
            pass

        return inst

    @lru_cache()
    def _get_or_create(self, hostname, zone, role, flavor):
        """Find if a instance exists Openstack.

        If instance is found return Instance instance with the info.
        If not found create a NIC and assign it to an Instance instance.
        """
        volume_config = {'image': self.image, 'class': self.storage_class}

        inst = self._get(hostname, zone, role)
        if inst:
            LOGGER.debug("Found instance %s", hostname)
            return inst

        LOGGER.debug("Creatig new instance %s", hostname)
        self.setup_networking()
        inst = Instance(self._cinder,
                        self._nova,
                        hostname,
                        self.net,
                        zone,
                        role,
                        volume_config,
                        flavor)
        inst.attach_port(self._neutron,
                         self.net['id'],
                         self.secgroups)

        return inst

    @property
    def netclient(self):
        """return the current network client"""
        return self._neutron

    @property
    def compute_client(self):
        """return the current compute client"""
        return self._nova

    @property
    def storage_client(self):
        """return the current storage client"""
        return self._cinder

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
                yield self._get_or_create(host, zone, 'master', self.master_flavor.id)

    def distribute_nodes(self):
        """
        distribute worker nodes in the different availability zones
        """
        hz = list(distribute_host_zones(self.nodes_names, self.azones))
        for hosts, zone in hz:
            for host in hosts:
                yield self._get_or_create(host, zone, 'node', self.node_flavor.id)

    def get_instances(self, role="node"):
        """Retrieve all nodes as Instances"""

        if role == "node":
            hz = list(distribute_host_zones(self.nodes_names, self.azones))
        else:
            hz = list(distribute_host_zones(self.management_names, self.azones))

        for hosts, zone in hz:
            for host in hosts:
                yield self._get(host, zone, role)
