"""
The dex module manages a dex installation
"""

from koris.cloud.openstack import LoadBalancer
from koris.util.net import is_port, is_ip
from koris.ssl import create_key, create_ca, CertBundle


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

        if not is_port(self.port):
            raise ValidationError(f"invalid pool port {self.port}")

        if self.algorithm not in self.allowed_algorithms:
            err = f"algorithm needs to be part of {self.allowed_algorithms}"
            raise ValidationError(err)

        if not self.members:
            raise ValidationError("pool needs members")

        if not isinstance(self.members, list):
            raise ValidationError("members need to be a list")

        for ip in self.members:
            if not is_ip(ip):
                raise ValidationError(f"invalid IP address: {ip}")

    def create(self, client, lb: LoadBalancer, listener_id):
        """Creates a Pool and adds it to a Listener"""

        self.verify()
        pool = lb.add_pool(client, listener_id=listener_id, lb_algorithm=self.algorithm,
                           protocol=self.protocol,
                           name=self.name)
        self.id = pool["id"]
        self.pool = pool

    def add_members(self, client, lb: LoadBalancer):
        """Adds Members to a Pool"""

        if not self.id:
            raise ValidationError("need pool id to add members")
        self.verify()

        for ip in self.members:
            lb.add_member(client, self.id, ip, self.port)

    def add_health_monitor(self, client, lb: LoadBalancer):
        """Adds a Health monitor to a Pool with default settings"""

        if not self.id:
            raise ValidationError("need pool id to create health monitor")
        self.verify()
        lb.add_health_monitor(client, self.id, f"{self.name}-health")

    def all(self, client, lb: LoadBalancer, listener_id):
        """Convenience function to create a Pool with Members and Health Monitor"""

        self.create(client, lb, listener_id)
        self.add_members(client, lb)
        self.add_health_monitor(client, lb)


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

        if not is_port(self.port):
            raise ValidationError(f"invalid listener port {self.port}")

    def create(self, client):
        """Create a new Listener and add it to the LoadBalancer"""
        self.verify()
        listener = self.loadbalancer.add_listener(client, name=self.name,
                                                  protocol=self.protocol,
                                                  protocol_port=self.port)
        self.listener = listener
        self.id = listener["listener"]["id"]

    def create_pool(self, client):
        """Creates a new Pool with members and healthmon and adds it to the Listener"""
        self.verify()
        if not self.listener:
            raise ValidationError("need listener to create pool")

        self.pool.all(client, self.loadbalancer, self.id)

    def all(self, client):
        """Creates a Listener and then adds a Pool to it"""

        self.create(client)
        self.create_pool(client)


class DexSSL:
    """Class managing the dex TLS infrastrucutre"""

    def __init__(self, 
                 cert_dir,
                 issuer: str,
                 k8s_ca_path="/etc/kubernetes/pki/oidc-ca.pem"):

        self.cert_dir = cert_dir
        self.k8s_ca_path = k8s_ca_path
        self.issuer = issuer

        self.ca_bundle = None
        self.client_bundle = None

        self.create_certs()

    def create_certs(self):
        """Create a CA and client cert for Dex

        Returns:
            Tuple consisting of root CA bundle and cert bundle
        """

        if not self.issuer:
            raise ValidationError("dex certificates needs an issuer")

        dex_ca_key = create_key()
        key_usage = [False, False, False, False, False, False, False, False, False]
        dex_ca = create_ca(dex_ca_key, dex_ca_key.public_key(),
                           "DE", "BY", "NUE", "Kubernetes", "dex", "kube-ca",
                           key_usage=key_usage)
        dex_ca_bundle = CertBundle(dex_ca_key, dex_ca)

        if is_ip(self.issuer):
            hosts, ips = "", [self.issuer]
        else:
            hosts, ips = [self.issuer], ""

        # digital_signature, content_commitment, key_encipherment
        key_usage = [True, True, True, False, False, False, False, False, False]
        dex_client_bundle = CertBundle.create_signed(dex_ca_bundle,
                                                     "DE", "BY", "NUE", "Kubernetes",
                                                     "dex-client", "kube-ca",
                                                     hosts=hosts, ips=ips,
                                                     key_usage=key_usage)

        self.ca_bundle = dex_ca_bundle
        self.client_bundle = dex_client_bundle

        return dex_ca_bundle, dex_client_bundle

    def save_certs(self, client_prefix="dex-client", ca_prefix="dex-ca"):
        """Saves dex client cert to disc"""

        if not self.client_bundle or not self.ca_bundle:
            raise ValidationError("create certificates before saving them")

        self.client_bundle.save(client_prefix, self.cert_dir)
        self.ca_bundle.save(ca_prefix, self.cert_dir)


async def create_dex(client, lb: LoadBalancer, name="dex",
                     listener_port=32000, pool_port=32000, protocol="HTTPS",
                     algo="ROUND_ROBIN", members=None):
    """Convenience function to create a Dex Listener and Pool"""

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.all(client)


async def create_oauth2(client, lb: LoadBalancer, name="oauth2",
                        listener_port=5555, pool_port=32555, protocol="HTTP",
                        algo="ROUND_ROBIN", members=None):
    """Convenience function to create OAuth2 Client App Listener and Pool"""

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.all(client)
