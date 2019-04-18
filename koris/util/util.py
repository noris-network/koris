"""
General purpose utilities
"""
import base64
import copy
import logging
import re
import time
import sys


from functools import lru_cache
from functools import wraps
from html.parser import HTMLParser
from pkg_resources import parse_version

import yaml

from koris.util.hue import red  # pylint: disable=no-name-in-module


def get_logger(name, level=logging.INFO):
    """
    return a logging.Logger instance which can be used
    in each module
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    # add ch to logger
    logger.addHandler(ch)
    return logger


KUBECONFIG_EMB = {'apiVersion': 'v1',
                  'clusters': [{
                      'cluster': {
                          'server': '%%%%MASTERURI%%%%',
                          'certificate-authority-data': '%%%%CA%%%%'
                      },
                      'name': 'kubernetes'
                  }],
                  'contexts': [{
                      'context': {
                          'cluster': 'kubernetes',
                          'user': '%%%USERNAME%%%'
                      },
                      'name': '%%%USERNAME%%%-context'
                  }],
                  'current-context': '%%%USERNAME%%%-context',
                  'kind': 'Config',
                  'users': [{
                      'name': '%%%USERNAME%%%',
                      'user': {
                          'client-certificate-data': '%%%%CLIENT_CERT%%%%',
                          'client-key-data': '%%%%CLIENT_KEY%%%%'
                      }
                  }]
                  }


def get_kubeconfig_yaml(master_uri, ca_cert, username, client_cert,
                        client_key, encode=False):
    """
    format a kube configuration file
    """
    config = copy.deepcopy(KUBECONFIG_EMB)
    config['clusters'][0]['cluster']['server'] = master_uri
    config['clusters'][0]['cluster']['certificate-authority-data'] = ca_cert
    config['contexts'][0]['context']['user'] = "%s" % username
    config['contexts'][0]['name'] = "%s-context" % username
    config['current-context'] = "%s-context" % username
    config['users'][0]['name'] = username
    config['users'][0]['user']['client-certificate-data'] = client_cert
    config['users'][0]['user']['client-key-data'] = client_key

    yml_config = yaml.dump(config)
    if encode:
        yml_config = base64.b64encode(yml_config.encode()).decode()
    return yml_config


def name_validation(name):
    """
    Validates a name that will be used as an instance name.
    Each name should conform to the following convention:
    not too long (maximum 244 characters)
    only ASCII-letters, numbers and dashes

    Args:
        name (str): The name to be checked

    Returns:
        Name if valid, Exits with Status code 2 if name is invalid.
    """
    if len(name) > 244:
        print(red("cluster-name is too long"))
        sys.exit(2)
    allowed = re.compile(r"^[a-zA-Z\d-]+$")
    if not allowed.match(name):
        print(red("cluster-name '{}' is using illegal characters. \
              Please change cluster-name in config file".format(name)))
        sys.exit(2)
    return name


@lru_cache(maxsize=16)
def host_names(role, num, cluster_name):
    """
    format host names
    """
    name_validation(cluster_name)
    return ["%s-%s-%s" % (cluster_name, role, i) for i in
            range(1, num + 1)]


def retry(exceptions, tries=4, delay=3, backoff=2, logger=None):
    """
    Retry calling the decorated function using an exponential backoff.

    Args:
        exceptions: The exception to check. may be a tuple of exceptions to check.
        tries: Number of times to try (not retry) before giving up.
        delay: Initial delay between retries in seconds.
        backoff: Backoff multiplier (e.g. value of 2 will double the delay each retry).
        logger: Logger to use. If None, print.
    """
    def deco_retry(f):  # pylint: disable=invalid-name

        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:  # pylint: disable=invalid-name
                    msg = '{}, Retrying in {} seconds...'.format(e,
                                                                 int(mdelay))
                    if logger:
                        logger(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry


class TitleParser(HTMLParser):  # pylint: disable=abstract-method
    """
    parse <title></title> from a given HTML page.
    """
    def __init__(self):
        HTMLParser.__init__(self)
        self.match = False
        self.title = ''

    def handle_starttag(self, tag,    # pylint: disable=arguments-differ
                        attributes):  # pylint: disable=unused-argument

        """handle the attributes of the page"""
        self.match = tag == 'title'

    def handle_data(self, data):
        if self.match:
            self.title = data
            self.match = False


class KorisVersionCheck:  # pylint: disable=too-few-public-methods
    """check the version published in the koris docs"""

    def __init__(self, html_string):

        parser = TitleParser()
        parser.feed(html_string)
        title = parser.title

        match = re.search(r"v\d\.\d{1,2}\.\d{1,2}\w*", title)
        try:
            version = match.group().lstrip("v")
            self.version = version
        except AttributeError:
            self.version = "0.0.0"

    def check_is_latest(self, current_version):
        """compare the published version on the docs to the current_version"""
        if parse_version(self.version) > parse_version(re.sub(r"\.dev\d*", "",
                                                              current_version)):
            print(red("Version {} of Koris was released, you should upgrade!".format(
                self.version)))
