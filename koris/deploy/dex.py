"""
The dex module manages a dex installation
"""

from ipaddress import ip_address


class ValidationError(Exception):
    """Raise a custom error if dex is configured inproperly"""


class Dex:
    """The Dex class manages a dex deployment into a Kubernetes cluster via koris.
    """

    def __init__(self, lb, members, name="dex"):
        self.loadbalancer = lb
        self.name = name
        self.protocol = "HTTPS"

        self.listener = None
        self.listener_port = 32000

        self.pool = None
        self.pool_algo = "ROUND_ROBIN"
        self.pool_members = members

        self.verify()

    def verify(self):
        """Verifies if dex can be deployed correctly.

        Raises:
            ValidationError: if dex is trying to be installed with invalid configuration

        """

        allowed_algos = ["ROUND_ROBIN", "LEAST_CONNECTIONS", "SOURCE_IP"]

        if not self.loadbalancer:
            raise ValidationError("Need LoadBalancer")

        if isinstance(self.listener_port, float):
            raise ValidationError(f"Invalid listener port {self.listener_port}")

        try:
            if not 0 <= self.listener_port <= 65535:
                raise ValidationError(f"Invalid listener port {self.listener_port}")
        except TypeError:
            raise ValidationError(f"Invalid listener port {self.listener_port}")

        if self.protocol != "HTTPS":
            raise ValidationError("Pool protocol needs to be HTTPS")

        if self.pool_algo not in allowed_algos:
            raise ValidationError(f"Pool protocol needs to be part of {allowed_algos}")

        if not isinstance(self.pool_members, list):
            raise ValidationError("Members need to be a list")

        if not self.pool_members:
            raise ValidationError("Pool needs members")

        for ip in self.pool_members:
            try:
                ip_address(ip)
            except ValueError:
                raise ValidationError(f"Invalid IP address: {ip}")

    async def create_dex_listener(self, client):
        """Creates a Listener for Dex"""

    async def create_oauth2_client_listener(self, client):
        """Create a Listener for the OAuth2 Callback app"""

    async def configure_lb(self, client):
        """Configures the LoadBalancer for dex."""

        # Check if all parameters are set correctly
        self.verify()
        lb = self.loadbalancer

        # Adding Listener to LB
        listener = lb.add_listener(client, name=f"{self.name}-listener",
                                   protocol=self.protocol,
                                   protocol_port=self.listener_port)
        listener_id = listener["listener"]["id"]
        self.listener = listener

        # Adding Pool to Listener
        pool = lb.add_pool(client, listener_id, lb_algorithm=self.pool_algo,
                           protocol=self.protocol, name=f"{self.name}-pool")
        pool_id = pool["id"]
        self.pool = pool

        # Adding Members to Pool
        for ip in self.pool_members:
            lb.add_member(client, pool_id, ip, self.listener_port)

        # Adding Healthmonitor to Pool
        lb.add_health_monitor(client, pool_id, name=f"{self.name}-health")
