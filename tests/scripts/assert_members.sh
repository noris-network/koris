
DESIRED_NUM=$1
CLUSTER_NAME=$2

CMD="openstack loadbalancer"
LB_NAME="${CLUSTER_NAME}-lb"

echo "Asserting that LoadBalancer ${LB_NAME} has ${DESIRED_NUM} members ..."

# Need to extract the Pool ID with cluster name since this will fail
# if there are multiple LoadBalancers / Clusters in the project such as in PI
LB_ID=$(${CMD} list -f value -c name -c id | grep ${LB_NAME} | awk '{print $1}')
POOL_ID=$(${CMD} show ${LB_ID} -f shell | grep pools | cut -d '=' -f2 | sed -e "s/\"//g")

ACTUAL_NUM=$(${CMD} member list ${POOL_ID} -f json -c address | jq '.| length')

if [ "${ACTUAL_NUM}" -ne "${DESIRED_NUM}" ]; then
	echo "Error: ${ACTUAL_NUM} members found:"
	${CMD} member list ${POOL_ID}
	exit 1
fi

echo "OK"

