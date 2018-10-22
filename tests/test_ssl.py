from kolt.ssl import create_certs

from flask import Flask
from multiprocessing import Process
from requests import request, exceptions
from time import sleep
from urllib3.util import connection
import certifi
import shutil
from tempfile import NamedTemporaryFile
from random import randint

config = {
    "n-nodes": 3,
    "n-masters": 3,
    "keypair": "otiram",
    "availibility-zones": ['nbg6-1a', 'nbg6-1b'],
    "cluster-name": "test",
    "private_net": "test-net",
    "security_group": "test-group",
    "image": "ubuntu 16.04",
    "node_flavor": "ECS.C1.4-8",
    "master_flavor": "ECS.C1.4-8",
    "storage_class": "Fast"
}


def test_sslcertcreation():
    ##########################################################
    # Variables for the whole test
    ##########################################################
    server_address = '127.0.0.1'
    server_port = 5000
    certificate_file_directory = 'certs-test'
    ca_file = "%s/ca.pem" % (certificate_file_directory,)
    ssl_key = "%s/kubernetes-key.pem" % (certificate_file_directory,)
    ssl_cert = "%s/kubernetes.pem" % (certificate_file_directory,)

    ##########################################################
    # Circumvent DNS resolving for this test
    ##########################################################
    _original_create_connection = connection.create_connection

    def all_localhost_create_connection(address, *args, **kwargs):
        host, port = address
        hostname = server_address

        return _original_create_connection((hostname, port), *args, **kwargs)

    connection.create_connection = all_localhost_create_connection

    ##########################################################
    # Create certificates for commonly used kubernetes names
    ##########################################################
    cluster_host_names = [
        "kubernetes.default", "kubernetes.default.svc.cluster.local",
        "kubernetes"]
    ips = ['127.0.0.1', "10.32.0.1"]
    create_certs(config, cluster_host_names, ips)

    ##########################################################
    # Patch ca certificates with ca created by koris.ssl
    ##########################################################
    ca_cert_file = certifi.where()
    ca_cert_backup_file = NamedTemporaryFile().name
    shutil.copyfile(ca_cert_file, ca_cert_backup_file)
    with open(ca_cert_file, 'a') as certfile:
        certfile.write(open(ca_file, 'r').read())

    ##########################################################
    # Start SSL Server on localhost with created certificates
    ##########################################################
    flask_testapp = Flask(__name__)

    @flask_testapp.route('/')
    def slash():
        return 'Passed'

    ssl_context = (ssl_cert, ssl_key)
    flask_testserver = Process(target=flask_testapp.run,
                               kwargs={'host': server_address,
                                       'port': server_port,
                                       'ssl_context': ssl_context})
    flask_testserver.start()

    ##########################################################
    # Test correct SSL connection for all given hostnames
    ##########################################################
    # Wait for Testserver to be started...
    sleep(2)
    ssl_failing = ['ssl-failing-host']
    connect_failing = ['connect-failing-host']
    ssl_failed = []
    connect_failed = []
    for hostname in cluster_host_names:
        try:
            request(url='https://%s:%d/' % (hostname, server_port),
                    method='GET').text
        except exceptions.SSLError:
            ssl_failed.append(hostname)
        except exceptions.ConnectionError:
            connect_failed.append(hostname)

    ##########################################################
    # Test fails actually fail
    ##########################################################
    for fail_hostname in ssl_failing:
        try:
            request(url='https://%s:%d/' % (fail_hostname, server_port),
                    method='GET').text
        except exceptions.SSLError:
            ssl_failed.append(fail_hostname)

    failport = randint(10000, 20000)
    while failport == server_port:
        failport = randint(10000, 20000)

    for fail_hostname in connect_failing:
        try:
            request(url='https://%s:%d/' % (fail_hostname, failport),
                    method='GET').text
        except exceptions.ConnectionError:
            connect_failed.append(fail_hostname)

    ##########################################################
    # Cleanup
    ##########################################################
    flask_testserver.terminate()
    shutil.copyfile(ca_cert_backup_file, ca_cert_file)
    shutil.rmtree(certificate_file_directory)

    ##########################################################
    # Assertions
    ##########################################################
    assert ssl_failed == ssl_failing
    assert connect_failed == connect_failing


if __name__ == '__main__':
    test_sslcertcreation()
