"""The dex module manages a dex (https://github.com/dexidp/dex) installation.

    The workflow is the following:

    1. Create certificates for Dex (via :class:`.DexSSL`)

    2. In :class:`koris.provision.cloud_init.FirstMasterInit` deploy the previously
    created CA to the first Master that is created. Additionally, create the extra
    arguments for the apiserver as environment variables in the ``koris.env`` file.

    3. In ``koris/provision/userdata/bootstraph-k8s-master-ubuntu-16.04.sh``, take the
    variables from ``koris.env`` and add their values as extra arguments to kubeadm's
    ``init.tmpl``.

    4. Take the main LoadBalancer and add two new Listeners to it: one for the Dex service
    (via :meth:`create_dex`) and one for an OAuth2 client app
    (via :meth:`create_oauth2`) that will be requesting tokens from Dex.

    Example:
        >>> dex_ssl = DexSSL("certs/", "dex.example.org")
        >>> dex_ssl.save_certs()
        >>> dex_conf = create_dex_conf(config['addons']['dex'], dex_ssl)
        >>> master_tasks = master_builder.create_masters_tasks(..., dex=dex_conf)
        >>> # Execute master_tasks
        >>> dex_listener = dex_conf['ports']['listener']
        >>> dex_service = dex_conf['ports']['service']
        >>> dex_members = master_ips
        >>> dex_task = loop.create_task(create_dex(NEUTRON, lbinst,
        ...                                        listener_port=dex_listener,
        ...                                        pool_port=dex_service,
        ...                                        members=dex_members))
        >>> client_listener = dex_conf['client']['ports']['listener']
        >>> client_service = dex_conf['client']['ports']['service']
        >>> client_members = node_ips
        >>> oauth_task = loop.create_task(create_oauth2(NEUTRON, lbinst,
        ...                                             listener_port=client_listener,
        ...                                             pool_port=client_service,
        ...                                             members=client_members))
        >>> tasks = [dex_task, oauth_task]
        >>> loop.run_until_complete(asyncio.gather(*tasks))
"""

from netaddr import valid_ipv4, valid_ipv6

from koris.cloud.openstack import LoadBalancer
from koris.ssl import create_key, create_ca, CertBundle


def is_port(port):
    """Checks if a port is valid.

    A port needs to be integer and between 0 and 65535.

    Args:
        port (int): The port to bee checked

    Returns:
        True, if port is valid
    """

    return isinstance(port, int) and 0 <= port <= 65535


def is_ip(ip):
    """Checks if an IP is a valid IPv4 or IPv6 address.

    Args:
        ip (str): The IP to be checked.

    Returns:
        True, if it's a valid IPv4 or IPv6 address
    """

    return valid_ipv4(ip) or valid_ipv6(ip)


class ValidationError(Exception):
    """A custom error if dex is configured inproperly"""


class Pool:
    """A Pool with Members, Algorithm and Port

    In future, this should be of the OpenStack scope instead of Dex's.

    When a Pool class gets instantiated, its parameters will be checked for validity.
    The same is true when functions get executed. Additionally, an instantiated class
    does not mean the pool is created with OpenStack.
    Use the ``create`` function for that.

    Members are loadbalanced IP Adresses or DNS Names that belong to a Pool. This Pool
    is then attached to a Listener.

    Example:
        >>> # Create a Pool with Members
        >>> members = ["10.0.0.1", 10.0.0.2"]
        >>> pool = Pool("test-pool", "HTTPS", 32443, "ROUND_ROBIN", members)
        >>> # Assuming we have a created Listener
        >>> pool.all(NEUTRON, LB, listener.id)

    Args:
        name (str): The name of the Pool.
        protocol (str): The protocol for the Pool. Must be part of ``allowed_protocols``.
        port (int): The port for the members.
        algorithm (str): The loadbalancing algorithm. Must be part of
            ``allowed_algorithms``.
        members (list): A list of members that the Pool contains.

    Attributes:
        allowed_algirthms (list): A list of strings for the LoadBalancer algorithms that
            can be used.
        allowed_protocols (list): A list of string for the LoadBalancer protocols that
            can be used.
        id (int): The pool ID. Will be assigned after ``create`` gets called.
        pool (dict): A LoadBalancer dictionary as received from the OpenStack API.
            Will be assigned after ``create`` gets called.

    """

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
        """Creates a Pool and adds it to a Listener.

        This function will set the attributes ``pool`` and ``id``.

        Args:
            client: An OpenStack client, usually Neutron.
            lb (LoadBalancer): An OSLoadBalancer instance.
            listener_id (str): The Listener ID this pool should be added to.
        """

        self.verify()
        pool = lb.add_pool(client, listener_id=listener_id, lb_algorithm=self.algorithm,
                           protocol=self.protocol,
                           name=self.name)
        self.id = pool["id"]
        self.pool = pool

    def add_members(self, client, lb: LoadBalancer):
        """Adds Members to a Pool.

        Args:
            client: An OpenStack client, usually Neutron.
            lb (LoadBalancer): An OSLoadBalancer instance.
        """

        if not self.id:
            raise ValidationError("need pool id to add members")
        self.verify()

        for ip in self.members:
            lb.add_member(client, self.id, ip, self.port)

    def add_health_monitor(self, client, lb: LoadBalancer):
        """Adds a Health monitor to a Pool with default settings

        Args:
            client: An OpenStack client, usually Neutron.
            lb (LoadBalancer): An OSLoadBalancer instance.
        """

        if not self.id:
            raise ValidationError("need pool id to create health monitor")
        self.verify()
        lb.add_health_monitor(client, self.id, f"{self.name}-health")

    def all(self, client, lb: LoadBalancer, listener_id):
        """Convenience function to create a Pool with Members and Health Monitor.

        Will call ``create``, ``add_members`` and ``add_health_monitor``.

        Args:
            client: An OpenStack client, usually Neutron.
            lb (LoadBalancer): An OSLoadBalancer instance.
            listener_id (str): The Listener ID this pool should be added to.
        """

        self.create(client, lb, listener_id)
        self.add_members(client, lb)
        self.add_health_monitor(client, lb)


class Listener:
    """A Listener containing a LoadBalancer and Pool.

    In future, this should be of the OpenStack scope instead of Dex's.

    When a Listener class gets instantiated, its parameters will be checked for validity.
    The same is true when functions get executed. Additionally, an instantiated class
    does not mean the pool is created with OpenStack.
    Use the ``create`` function for that.

    A Pool (see above) is attached to a Listener. This Listener listens on a specific port
    and forwards traffic to the Pool, on a specific port. A Listener is attached to a
    LoadBalancer which will forward traffic to a specific Listener, depending on the port.

    Example:
        >>> # Create a Pool with Members
        >>> members = ["10.0.0.1", 10.0.0.2"]
        >>> pool = Pool("test-pool", "HTTPS", 32443, "ROUND_ROBIN", members)
        >>> listener = Listener(LB, "test-listener", 443, pool)
        >>> # This will create the Pool, add it to the Listener and add it all to a LB
        >>> listener.all(NEUTRON)

    Args:
        lb (LoadBalancer): An OpenStack LoadBalancer Object.
        name (str): The name of the Listener.
        port (int): The port which will be listened on.
        protocol (str): The protocol that should be used for listening. Must be part of
            ``allowed_protocols``.
        pool (Pool): A Pool object.

    Attributes:
        allowed_algirthms (list): A list of strings for the LoadBalancer algorithms that
            can be used.
        allowed_protocols (list): A list of string for the LoadBalancer protocols that
            can be used.
        loadbalancer (LoadBalancer): An OpenStack LoadBalancer Object
        id (int): The Listener ID. Will be assigned after ``create`` gets called.
        listener (dict): A LoadBalancer dictionary as received from the OpenStack API.
            Will be assigned after ``create`` gets called.
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
        """Creates a new Listener and adds it to the LoadBalancer.

        This function will assing the attributes ``listener`` and ``id``.

        Args:
            client: An OpenStack client, usually Neutron.
        """
        self.verify()
        listener = self.loadbalancer.add_listener(client, name=self.name,
                                                  protocol=self.protocol,
                                                  protocol_port=self.port)
        self.listener = listener
        self.id = listener["listener"]["id"]

    def create_pool(self, client):
        """Creates a new Pool with members and healthmon and adds it to the Listener.

        Requires ``create`` to be called first.

        In case the ``Pool.create()`` or ``Pool.all()`` function hasn't been called,
        call ``Pool.all()``.

        Args:
            client: An OpenStack client, usually Neutron.

        """
        self.verify()
        if not self.listener:
            raise ValidationError("need listener to create pool")

        self.pool.all(client, self.loadbalancer, self.id)

    def all(self, client):
        """Convenience function to create a Listener, then Pool.

        Will call ``create`` and ``create_pool``.

        Args:
            client: An OpenStack client, usually Neutron.
        """

        self.create(client)
        self.create_pool(client)


class DexSSL:
    """Class managing the dex TLS infrastrucutre.

    Dex uses a self-signed CA to sign tokens it receives from a OIDC Provider
    such as Gitlab, GitHub or LDAP. A 3rd Party (such as the Kubernetes apiserver)
    will then verify the signed token with Dex's public key. A client certificate,
    that is signed by the Dex CA, is used to request a token from Dex.

    On instantiation, will create the Dex CA and client cert bundles.

    Example:
        >>> dex_ssl = DexSSL("./certs", "dex.example.com")
        >>> dex_ssl.save_certs()

    Args:
        cert_dir (str): The directory where the keys and certificates will be
            saved to.
        issuer (str): The issuer of the Dex CA. This needs to be an IP or DNS
            where Dex is reachable from a host and from inside the
            kube-apiserver.
        k8s_ca_path (str): This is the location on the Master node(s) where
            the Dex CA will saved under. Needs to be a full path including
            file name. This will then be passed as an argument to the
            kube-apiserver so it can use the certificate's public key
            to verify an incoming token.

    Attributes:
        ca_bundle (:class:`koris.ssl.CertBundle`): An SSL Certificate Bundle
            containing the Dex CA certificate and key pair.
        client_bundle(:class:`koris.ssl.CertBundle`): An SSL Certificate Bundle
            containing the client certificate and key pair.
    """

    def __init__(self,
                 cert_dir: str,
                 issuer: str,
                 k8s_ca_path="/etc/kubernetes/pki/oidc-ca.pem"):

        self.cert_dir = cert_dir
        self.k8s_ca_path = k8s_ca_path
        self.issuer = issuer

        self.ca_bundle: CertBundle = None
        self.client_bundle: CertBundle = None

        self.create_certs()

    def create_certs(self):
        """Create a CA and client cert for Dex.

        Will first create a CA bundle, then use this to sign a client certificate.
        The Client cert will have the following Key Usage parameters: Digital Signature,
        Content Commitment, Key Encipherment.

        Will also set the attributes ``ca_bundle`` and ``client_bundle``.

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
        """Saves certificate bundles to disc.

        This function uses :meth:`koris.ssl.CertBundle.save` to save the certificate
        bundles to disc.

        Args:
            client_prefix (str): The prefix for the client certificate.
            ca_prefix (str): The prefix for the Dex CA.
        """

        if not self.client_bundle or not self.ca_bundle:
            raise ValidationError("create certificates before saving them")

        self.client_bundle.save(client_prefix, self.cert_dir)
        self.ca_bundle.save(ca_prefix, self.cert_dir)


async def create_dex(client, lb: LoadBalancer, name="dex",
                     listener_port=32000, pool_port=32000, protocol="HTTPS",
                     algo="ROUND_ROBIN", members=None):
    """Convenience function to create a Dex Listener and Pool.

    This will take an existing LoadBalancer in OpenStack and adds a new Listener
    with Pool and members to it, so Dex can be reached inside the cluster.

    Will first create a :class:`.Pool`, then a :class:`.Listener` from that pool.

    Args:
        lb (LoadBalancer): The used LoadBalancer.
        name (str): The name of the Dex Listener and Pool.
        listener_port (int): The port the Listener should listen on.
        pool_port (int): The exposed port of the Dex service inside the cluster.
        protcol (str): The protocol to use. Should be HTTPS.
        algo (str): The loadbalancing algorithm to use.
        members (list): A list of members to add to the pool. Should be the Masters.
    """

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.all(client)


async def create_oauth2(client, lb: LoadBalancer, name="oauth2",
                        listener_port=5556, pool_port=32555, protocol="HTTP",
                        algo="ROUND_ROBIN", members=None):
    """Convenience function to create an OAuth2 Client App Listener and Pool.

    Users need to deploy an OAuth2 Client App that talks with Dex to retrieve a
    token. This function takes an existing LoadBalancer in OpenStack and adds a
    new Listener with Pool and Members to it. This way, clients  and Dex
    can reach the OAuth2 Client App.

    Args:
        lb (LoadBalancer): The used LoadBalancer.
        name (str): The name of the OAuth2 Listener and Pool.
        listener_port (int): The port the Listener should listen on.
        pool_port (int): The exposed port of the OAuth2 service inside the cluster.
        protcol (str): The protocol to use. Should be HTTPS.
        algo (str): The loadbalancing algorithm to use.
        members (list): A list of members to add to the pool. Should be the Nodes.
    """

    pool = Pool(f"{name}-pool", protocol, pool_port, algo, members)
    listener = Listener(lb, f"{name}-listener", listener_port, pool)
    listener.all(client)


# pylint: disable=too-many-branches
def create_dex_conf(config, dex_ssl: DexSSL):
    """Parse the koris config for dex parameters.

    The user needs to validate first if dex is wished to be installed.
    The following config arguments are optional username_claim (default: email),
    groups_claim (default: group)

    Args:
        config (dict): The config['addons']['dex'] part of the config dict.
        dex_ssl (DexSSL): a DexSSL instance.

    Raises:
        ValidationError if mandatory parts are missing or incorrect information
            has been provided.

    Returns:
        A dictionary with the correct config parameters set.
    """

    # Validation
    if not config:
        raise ValidationError("missing config paramaters")

    if "ports" not in config:
        raise ValidationError("requires ports to be set")

    for arg in ["listener", "service"]:
        if arg not in config["ports"]:
            raise ValidationError(f"under 'ports', need '{arg}'")
        for port in config["ports"].values():
            if not is_port(port):
                raise ValidationError(f"invalid port '{port}'")

    if "client" not in config:
        raise ValidationError("requires client app information")

    for arg in ["id", "ports"]:
        if arg not in config["client"]:
            raise ValidationError(f"under 'client', need '{arg}'")

    for arg in ["listener", "service"]:
        if arg not in config["client"]["ports"]:
            raise ValidationError(f"under 'client:ports', need '{arg}'")
        for port in config["client"]["ports"].values():
            if not is_port(port):
                raise ValidationError(f"invalid port '{port}'")

    username_claim, groups_claim = "", ""
    if 'username_claim' not in config:
        username_claim = "email"
    else:
        username_claim = config["username_claim"]

    if 'groups_claim' not in config:
        groups_claim = "groups"
    else:
        groups_claim = config["username_claim"]

    return {
        "issuer": f"{dex_ssl.issuer}",
        "cert": dex_ssl.ca_bundle.cert,
        "ca_file": dex_ssl.k8s_ca_path,
        "username_claim": username_claim,
        "groups_claim": groups_claim,
        "ports": {
            "listener": config['ports']['listener'],
            "service": config['ports']['service'],
        },
        "client": {
            "id": "example-app",
            "ports": {
                "listener": config['client']['ports']['listener'],
                "service": config['client']['ports']['service'],
            }
        }
    }
