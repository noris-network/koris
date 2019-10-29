#!/bin/bash
# Asserts that a certain number of pods are Running.

set -e

export KUBECONFIG=${KUBECONFIG}

function checkpod() {
    local name=$1
    STATUS=$(kubectl -n ${NAMESPACE} -o jsonpath='{.status.phase}' get po ${name})
    if [ "Running" == "${STATUS}" ]; then
	echo "$name is fine!"
        return 0
    fi
    return 1
}

for (( j=1; j<=${NUM}; j++ )); do
    name="${POD_NAME}-${CLUSTER_NAME}-master-"
    number=$j
    for i in $(seq 1 60); do checkpod ${name}${number} && break;
	sleep 15;
	if [ $i -eq 60 ]; then
            echo "Pod $j not ready, dumping debug information"
            kubectl -n ${NAMESPACE} describe pod/${name}${number}
            kubectl -n ${NAMESPACE} logs ${name}${number}
	fi
    done
done
