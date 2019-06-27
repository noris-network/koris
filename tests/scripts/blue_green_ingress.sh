#!/bin/bash

set -e

export KUBECONFIG=${KUBECONFIG}
export LBIP=""

DIRECTORY="$(cd "$(dirname "$0")" && pwd)"

function apply_all() {
	kubectl create configmap welcome-green \
		--from-file "${DIRECTORY}/../integration/welcome-green.html"
	kubectl create configmap welcome-blue \
		--from-file "${DIRECTORY}/../integration/welcome-blue.html"

	kubectl create -f "${DIRECTORY}/../integration/nginx-green.yml"
	kubectl create -f "${DIRECTORY}/../integration/nginx-blue.yml"
	kubectl create -f "${DIRECTORY}/../integration/blue-green-fan.yml"
}
function get_info() {
	kubectl get ingress
	kubectl describe ingress name-virtual-host-ingress
	LBIP=$(kubectl config view -o json | jq -r '.clusters[0].cluster.server | sub("https://"; "") | sub(":6443";  "")')
	echo "LoadBalancer IP is ${LBIP}"
}

function test() {

	for color in blue green; do
		echo "${LBIP} ${color}.bar.com" >> /etc/hosts
		cat /etc/hosts
		OK=0
		for i in $(seq 1 60); do
			curl -qs "${color}.bar.com" | grep $color && { OK=1; break; }
			echo "waiting 1 sec"
			sleep 1
		done

		if [ ${OK} -eq 0 ]; then echo "fetching $color failed"; exit 1; fi
	done
}

apply_all
get_info
test
