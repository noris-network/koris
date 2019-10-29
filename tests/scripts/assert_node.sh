#!/bin/bash
# Perform several actions regarding nodes

# Take NODE_NAME from env, else set to empty
: ${NODE_NAME:=""}
if [ -z "${NODE_NAME}" ]; then
    echo "Error: env NODE_NAME is empty"
    exit 1
fi

# Check if a node has left a k8s cluster
function deleted() {
    echo "Checking if ${NODE_NAME} has left the cluster ..."
    for i in {1..5}
    do
        kubectl describe nodes --kubeconfig=${KUBECONFIG} ${NODE_NAME}
        if [ $? -eq 1 ]; then
            echo "OK"
            exit 0
        fi
        echo "Node ${NODE_NAME} still up, sleeping for 10s ... "
        sleep 10s
    done

    echo "Timeout while waiting for ${NODE_NAME} to leave cluster"
    exit 1
}

# Check if a node is in status Ready.
function ready() {
    echo "Checking if ${NODE_NAME} is ready ..."
    for i in {1..12}
    do
        kubectl describe nodes --kubeconfig=${KUBECONFIG} ${NODE_NAME} | grep -q "kubelet is posting ready status"
        if [ $? -eq 0 ]; then
            echo "OK"
            exit 0
        fi
        echo "Node ${NODE_NAME} doesn't seem to be up yet, sleeping for 30s ... "
        sleep 30s
    done

    echo "Timeout while waiting for ${NODE_NAME} to become ready"
    exit 1
}

# Assert labels on a worker node.
function labels() {
    echo "Asserting node labels on ${NODE_NAME} ..."
    for i in {1..20}
    do
        kubectl describe nodes --kubeconfig=${KUBECONFIG} ${NODE_NAME} | grep -q failure-domain.beta.kubernetes.io/region=de-nbg6-1
        if [ $? -eq 0 ]; then
            echo "OK"
            exit 0
        fi
        echo "Node ${NODE_NAME} doesn't seem to be up yet, sleeping for 30s ... "
        sleep 30s
    done

    echo "Timeout while trying to assert labels of ${NODE_NAME}"
    exit 1
}

# Assert that a node has been deleted from OpenStack
function deleted-openstack() {
    echo "Asserting that ${NODE_NAME} has been removed from OpenStack ..."
    for i in {1..20}
    do
        openstack server list -f value -c Name | grep -q ${NODE_NAME}
        if [ $? -eq 1 ]; then
            echo "OK"
            exit 0
        fi
        echo "Node ${NODE_NAME} still up, sleeping for 5s ..."
        sleep 10s
    done

    echo "Node ${NODE_NAME} still present in OpenStack:"
    openstack server list
    exit 1
}

function usage() {
    echo "Usage:"
    echo -e "$0 deleted\t\t\tChecks if node has been deleted from the cluster."
    echo -e "$0 ready\t\t\tChecks if node is in status Ready."
    echo -e "$0 labels\t\t\tChecks if node has correct node labels."
    echo -e "$0 deleted-openstack\tChecks if the has been deleted from OpenStack"
    echo
    echo "Requires environment variabel NODE_NAME to be set."
}

# -----------------------------

if [ "$1" == "help" ]; then
    usage
elif [ "$1" == "deleted" ]; then
    deleted
elif [ "$1" == "ready" ]; then
    ready
elif [ "$1" == "labels" ]; then
    labels
elif [ "$1" == "deleted-openstack" ]; then
    deleted-openstack
elif [ $# -eq 0 ]; then
    echo "No arguments supplied."
    echo
    usage
    exit 1
else
    echo "Unrecognized option '$1'"
    echo
    usage
    exit 1
fi
