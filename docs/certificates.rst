.. highlight:: shell

============
Certificates
============

CA structure
------------

The setup currently consists of a CA certificate (ca.pem) with three 
descendants: admin, kubelet and service-account.

Example:
ca: 
  subject= /C=DE/ST=Bayern/L=NUE/O=Kubernetes/OU=CDA-PI/CN=kubernetes
admin: 
  subject= /C=DE/ST=Bayern/L=NUE/O=system:masters/OU=CDA-PI/CN=admin
kubelet: 
  subject= /C=DE/ST=Bayern/L=NUE/O=system:masters/OU=CDA-PI/CN=kubelet
service-account: 
  subject= /C=DE/ST=Bayern/L=NUE/O=Kubernetes/OU=CDA-PI/CN=service-accounts


