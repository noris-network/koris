
DESIRED_NUM=$1
CLUSTER_NAME=$2

CMD="openstack loadbalancer"


POOLID="$(${CMD} pool show "${CLUSTER_NAME}-lb-pool" -f value -c id)"

ACTUAL_NUM=$(${CMD} member list "${POOLID}" -f json -c address | jq '.| length')

if [ "${ACTUAL_NUM}" -ne "${DESIRED_NUM}" ]; then
	exit 1
fi

