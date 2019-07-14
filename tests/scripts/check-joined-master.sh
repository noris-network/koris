#!/bin/bash
set -x

NUM=${NUM:-4}
MASTER_NAME="$CLUSTER_NAME-master-${NUM}"
KUBECONFIG=${KUBECONFIG}

# look for a log message in the cloud init log
function find_stage() {
    STAGE=$1
    openstack console log show ${MASTER_NAME} | grep "${STAGE}"
}

echo "Scrutinizig logs for ${MASTER_NAME}"

STAGES=( 'Started write_join_config' 'Finished write_join_config' 'Success!')

sleep 60 # initial sleep for waiting that the master boots

for ((i = 0; i < ${#STAGES[@]}; i++)); do
	until find_stage "${STAGES[$i]}"; do
		echo "Waiting for stage ${STAGES[$i]}"
		sleep 10
	done
	echo "${STAGES[$i]}"
done

if [ $(kubectl get nodes --kubeconfig=${KUBECONFIG} -l node-role.kubernetes.io/master -o name | grep -c master) -ne ${NUM} ]; \
then
	echo "can't find $(NUM) masters";
	kubectl get nodes --kubeconfig=${KUBECONFIG};
	exit 1;
else
	echo "OK";
fi
