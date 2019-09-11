#!/bin/bash

set -e

DESIRED_NUM=$1
CLUSTER_NAME=$2
POOL_NAME=$3

CMD="openstack loadbalancer"
LB_NAME="${CLUSTER_NAME}-lb"
echo "Asserting that LoadBalancer ${LB_NAME} has ${DESIRED_NUM} members ..."

# Need to extract the Pool ID with cluster name since this will fail
# if there are multiple LoadBalancers / Clusters in the project such as in PI
LB_ID=$(${CMD} list -f value -c name -c id | grep ${LB_NAME} | awk '{print $1}')

echo LB_ID ${LB_ID}
if [ -z ${LB_ID} ]; then
	exit 1
fi

POOL_ID=$(${CMD} pool list -f value -c name -c id  | grep ${POOL_NAME}\$ | cut -d" " -f 1)

ACTUAL_NUM=$(${CMD} member list -f json -c address ${POOL_ID} | jq '.| length')

if [ "${ACTUAL_NUM}" -ne "${DESIRED_NUM}" ]; then
	echo "Error: ${ACTUAL_NUM} members found:"
	${CMD} member list ${POOL_ID}
	exit 1
fi

echo "OK"

