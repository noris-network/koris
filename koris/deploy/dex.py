"""
The dex module manages a dex installation
"""

from ipaddress import ip_address

from koris.cloud.openstack import LoadBalancer


def port_ok(port):
    """Checks if a port is valid"""
    try:
        if not 0 <= port <= 65535:
            return False
    except TypeError:
        return False

    return True


class ValidationError(Exception):
    """Raise a custom error if dex is configured inproperly"""


class Pool:
    """A Pool with Members, Algorithm and Port"""

    def __init__(self, name, protocol, port, algorithm, members):
        self.allowed_algorithms = ["ROUND_ROBIN", "LEAST_CONNECTIONS", "SOURCE_IP"]
        self.allowed_protocols = ["HTTPS", "HTTP", "TCP", "TERMINATED_HTTPS"]

        self.name = name
        self.protocol = protocol
        self.port = port
        self.algorithm = algorithm
        self.members = members

        self.verify()

        # Can be set later
        self.id = None
        self.pool = None

    def verify(self):
        """Checks if a Pool is configured correctly"""

        if self.protocol not in self.allowed_protocols:
            err = f"protocol needs to be part of {self.allowed_protocols}"
            raise ValidationError(err)

        if not port_ok(self.port):
            raise ValidationError(f"invalid pool port {self.port}")

        if self.algorithm not in self.allowed_algorithms:
            err = f"algorithm needs to be part of {self.allowed_algorithms}"
            raise ValidationError(err)
        
        if not self.members:
            raise ValidationError("pool needs members")

        if not isinstance(self.members, list):
            raise ValidationError("members need to be a list")

        for ip in self.members:
            try:
                ip_address(ip)
            except ValueError:
                raise ValidationError(f"invalid IP address: {ip}")

    def create(self, client, lb: LoadBalancer, listener_id):
        """Adds the Pool to a Listener"""

        pool = lb.add_pool(client, listener_id=listener_id, lb_algorithm=self.algorithm,
                           protocol=self.protocol,
                           name=self.name,
                           protocol_port=self.port)
        self.id = pool["id"]
        self.pool = pool

    def add_health_monitor(self, client, lb: LoadBalancer):
        """Adds a Health monitor to a Pool with default settings"""

        if not self.id:
            raise ValidationError("need pool id to create health monitor")

        lb.add_health_monitor(client, self.id, f"{self.name}-health")


class Listener:
    """The Listener class holds all information for a LB listener.

    A listener is attached to a LoadBalancer and consits of a Pool.
    A Pool consists of 1+ members, which are checked by a Healthmonitor

    In the future, this should be refactored to an OpenStack class OSListener.

    Args:
        lb (openstack.LoadBalancer): an OpenStack LoadBalancer Object
        name (str): the name for the Listener

    """

    def __init__(self, lb: LoadBalancer, name, port, pool: Pool, protocol="HTTPS"):
        self.allowed_protocols = ["HTTPS", "HTTP", "TCP", "TERMINATED_HTTPS"]
        self.loadbalancer = lb
        self.name = name
        self.port = port
        self.protocol = protocol
        self.pool = pool

        self.verify()

        # Will be set later
        self.listener = None
        self.id = None

    def verify(self):
        """Verifies if the Listener is configured correctly"""

        if not self.loadbalancer:
            raise ValidationError("listener needs LoadBalancer")

        if not port_ok(self.port):
            raise ValidationError(f"invalid listener port {self.port}")

    def create_listener(self, client):
        """Create a new Listener and add it to the LoadBalancer"""

        listener = self.loadbalancer.add_listener(client, name=f"{self.name}-listener",
                                                  protocol=self.protocol,
                                                  protocol_port=self.port)
        self.listener = listener
        self.id = listener["listener"]["id"]

    def create_pool(self, client):
        """Creates a new Pool with members and healthmon and adds it to the Listener"""

        if not self.listener:
            raise ValidationError("need listener to create pool")

        self.pool.create(client, self.loadbalancer, self.id)
        self.pool.add_health_monitor(client, self.loadbalancer)

    def create_all(self, client):
        """Creates a Listener and then adds a Pool to it"""

        self.create_listener(client)
        self.create_pool(client)


async def create_dex(client, lb: LoadBalancer, name="dex",
                     listener_port=32000, pool_port=32000, protocol="HTTPS",
                     algo="ROUND_ROBIN", members=None):
    """Convenience function to create a Dex Listener and Pool"""

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.create_all(client)


async def create_oauth2(client, lb: LoadBalancer, name="oauth2",
                        listener_port=5556, pool_port=32555, protocol="HTTP",
                        algo="ROUND_ROBIN", members=None):
    """Convenience function to create OAuth2 Client App Listener and Pool"""

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.create_all(client)
