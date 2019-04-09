#!/bin/bash
# Asserts that a certain number of pods are Running.

set -e

CURR=0
MAX=10

for (( i=1; i<=${NUM}; i++ )); do
    TO_CHECK="${POD_NAME}-${i}-${CLUSTER_NAME}"
    echo -n "Checking if ${TO_CHECK} is available: "
    for (( j=1; j<=${MAX}; j++ )); do
        STATUS=$(kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} -o jsonpath='{.status.phase}' get po ${TO_CHECK})
        if [ "Running" == "${STATUS}" ]; then
            echo "-- OK"
            break
        fi
        sleep 15
        echo -n "."
        CURR=$(expr ${CURR} + 1)
    done

    if [ "${CURR}" -eq ${MAX} ]; then
        echo
        echo "Pod not ready, dumping debug information"
        kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} describe pod/${TO_CHECK}
        kubectl --kubeconfig=${KUBECONFIG} -n ${NAMESPACE} logs ${TO_CHECK}
        exit 1
    fi
done

