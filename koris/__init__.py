# pylint: disable=missing-docstring
try:
    import pkg_resources
    __version__ = pkg_resources.get_distribution('koris').version
except pkg_resources.DistributionNotFound:
    __version__ = '1.2.1'

# Defining some constants
MASTER_PREFIX = "master"
MASTER_LISTENER_NAME = f"{MASTER_PREFIX}-listener"
MASTER_POOL_NAME = f"{MASTER_PREFIX}-pool"
KUBERNETES_BASE_VERSION = "1.13.10"
