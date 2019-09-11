#!/bin/bash

kubectl --kubeconfig=${KUBECONFIG} apply -f tests/integration/default-storageClass-de-nbg6-1a.yml
kubectl --kubeconfig=${KUBECONFIG} apply -f tests/integration/default-storageClass-de-nbg6-1b.yml
kubectl --kubeconfig=${KUBECONFIG} apply -f tests/integration/pvcs.yml

echo "Waiting for volumes to bind"
NVOLUMES=$(kubectl --kubeconfig=${KUBECONFIG} get pvc --kubeconfig=${KUBECONFIG} | grep -ci bound)
while true; do \
	if [ $NVOLUMES -eq 2 ]; then \
		break; \
	fi; \
	NVOLUMES=$(kubectl --kubeconfig=${KUBECONFIG} get pvc --kubeconfig=${KUBECONFIG} | grep -ci bound)
	sleep 1; \
	echo -n "."; \
done;
