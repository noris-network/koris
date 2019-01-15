# pylint: disable=missing-docstring
try:
    import pkg_resources
    __version__ = pkg_resources.get_distribution('koris').version
except pkg_resources.DistributionNotFound:
    __version__ = '0.9-dev'
