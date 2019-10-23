#!/bin/bash

##
# test that k8s can create a loadbalancer with a floating IP as part of
# integration test.
##

set -eu
export LB="kube_service_kubernetes_default_external-http-nginx-service"

echo "waiting for loadbalancer to become active"
until openstack loadbalancer show -c provisioning_status -f value $LB | grep -q "ACTIVE"; do
	echo -n "."
	sleep 2;
done


IP=$(openstack floating ip list -c "Fixed IP Address" -c "Floating IP Address" -f value | \
	grep $(openstack loadbalancer show ${LB} -f value -c vip_address) | cut -d" " -f 1)

echo "Loadbalancer IP:" "${IP}";
echo "Waiting for service to become available:"
until curl -s http://${IP}:80; do echo -n "."; sleep 1; done;
