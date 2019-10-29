#!/bin/bash

export KUBECONFIG=${KUBECONFIG}

for i in $(seq 1 ${NUM}); do
	kubectl get pod -n kube-system kube-apiserver-${CLUSTER_NAME}-master-${i} -o json | jq -r -e '.spec.containers[0].volumeMounts[] | select(.mountPath=="/var/log/kubernetes")'
	kubectl get pod -n kube-system kube-apiserver-${CLUSTER_NAME}-master-${i} -o json | jq -r -e '.spec.containers[0].volumeMounts[] | select(.mountPath=="/etc/kubernetes/audit-policy.yml")'
	kubectl get pod -n kube-system kube-apiserver-${CLUSTER_NAME}-master-${i} -o json | jq -e -r '.spec.containers[0].command | index("--audit-policy-file=/etc/kubernetes/audit-policy.yml")'
done
