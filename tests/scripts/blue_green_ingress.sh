#!/bin/bash

set -e

export KUBECONFIG=${KUBECONFIG}
export LBIP=""

colors=( blue.bar.com green.bar.com )

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
	if [ -z  "${LBIP}" ]; then
		get_info
	fi
	if [ ${UID} -eq 0 ]; then
		echo "${LBIP} ${colors[*]}" >> /etc/hosts
	else
		echo "${LBIP} ${colors[*]}" | sudo -E tee -a /etc/hosts
	fi
	for color in blue green; do
		cat /etc/hosts;
		OK=0
		for i in $(seq 1 60); do
			curl -qs "${color}.bar.com" | grep $color && { OK=1; break; }
			echo "waiting 1 sec"
			sleep 1
		done

		if [ ${OK} -eq 0 ]; then echo "fetching $color failed"; exit 1; fi
	done
}

function clean() {
	kubectl delete configmap welcome-green || echo "not found"
	kubectl delete configmap welcome-blue || echo "not found"
	kubectl delete -f "${DIRECTORY}/../integration/nginx-green.yml" || echo "not found"
	kubectl delete -f "${DIRECTORY}/../integration/nginx-blue.yml" || echo "not found"
	kubectl delete -f "${DIRECTORY}/../integration/blue-green-fan.yml" || echo "not found"
	if [ ${UID} -eq 0 ]; then
		sed -i '/'"${colors[1]}"'/d' /etc/hosts
	else
		sudo -E sed -i '/'"${colors[1]}"'/d' /etc/hosts
	fi

}

function main() {
	if [ -n "$1" ]; then
		"$1"
	else
		apply_all
		get_info
		test
		clean
	fi
}

(return 0 2>/dev/null) && sourced=1 || sourced=0

if [[ $sourced == 1 ]]; then
	set +e
	printf "You can now use any of these functions:\n"
	grep "^function" "${BASH_SOURCE}" | cut -d " " -f 2 | tr -d '()'
else
	main "$@"
fi
