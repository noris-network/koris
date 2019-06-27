#!/bin/bash

set -e

MAX=${MAX:-10}  # max tries

JSON_PATH='{.items[0].status.phase}'

for (( i=1; i<=MAX; i++ )); do
    	echo -n "Checking if pod is available: "
	STATUS=$(kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} get po ${TO_CHECK}  -o jsonpath=${JSON_PATH})
        if [ "Running" == "${STATUS}" ]; then
            echo "-- OK"
            exit 0
        fi
        sleep 15
        echo -n "."
done

echo "Pod not ready, dumping debug information"
kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} describe pod ${TO_CHECK}
kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} logs ${TO_CHECK}
exit 1
