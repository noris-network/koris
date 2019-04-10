
DESIRED_NUM=$1
# CLUSTER_NAME=$2

CMD="openstack loadbalancer"

# TODO: in the paste pools had the cluster name in them
# this is now removed
POOLID="$(${CMD} pool show "master-pool" -f value -c id)"

ACTUAL_NUM=$(${CMD} member list "${POOLID}" -f json -c address | jq '.| length')

if [ "${ACTUAL_NUM}" -ne "${DESIRED_NUM}" ]; then
	exit 1
fi

