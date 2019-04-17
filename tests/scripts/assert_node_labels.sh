#!/bin/bash
# Might take up to 5 minutes before node is launched and configured

for i in {1..10}
do
    kubectl describe nodes --kubeconfig=${KUBECONFIG} koris-pipe-line-${CLUSTER_NAME}-node-${NUM} | grep -q failure-domain.beta.kubernetes.io/region=de-nbg6-1
    if [ $? -eq 0 ]; then
        echo "OK"
        exit 0
    fi
    echo "Node doesn't seem to be up yet, sleeping for 30s ... "
    sleep 30s
done

echo "Unable to assert node labels"
exit 1