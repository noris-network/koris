#!/bin/bash

##
# test that k8s can create a loadbalancer with a floating IP as part of
# integration test.
##

set -eux

export LB="kube_service_kubernetes_default_external-http-nginx-service"

# add a floating IP so one isn't assigned
EXTERNAL_IP=$(openstack floating ip create c019250b-aea8-497e-9b3b-fd94020684b6 -f value -c floating_ip_address || echo "Quota exceeded")

if [[ ${EXTERNAL_IP} =~ "Quota exceeded" ]]; then
	EXTERNAL_IP=$(openstack floating ip list -c 'Fixed IP Address' -c 'Floating IP Address' -f value |  grep None | cut -d" " -f 1 | head -n 1)
fi

echo ${EXTERNAL_IP};

sed -i 's/%%FLOATING_IP%%/'${EXTERNAL_IP}'/' tests/integration/nginx-deployment.yml
kubectl apply -f tests/integration/nginx-deployment.yml --kubeconfig=${KUBECONFIG}

echo "waiting for loadbalancer to become active"
until openstack loadbalancer show -c provisioning_status -f value $LB | grep -q "ACTIVE"; do
	echo -n "."
	sleep 2;
done

echo "Loadbalancer IP:" "${EXTERNAL_IP}";
echo "Waiting for service to become available:"
until curl -s http://${EXTERNAL_IP}:80; do echo -n "."; sleep 1; done;
