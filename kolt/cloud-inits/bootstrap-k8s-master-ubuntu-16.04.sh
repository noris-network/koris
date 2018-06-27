#!/bin/bash 

# bootstrap k8s master without kubeadm


K8S_VERSION=v1.10.4



#### Do NOT edit anything below


# install the K8S api server

K8S_URL=https://storage.googleapis.com/kubernetes-release/release/
OS=liux
BIN_PATH=/usr/bin/

for item in "apiserver controller-manager scheduler"; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/amd64/kube-${item} -o ${BIN_PATH}/${item}
    chmod +x ${BIN_PATH}/${item}
done


curl ${K8S_VERSION}/bin/${OS}/amd64/kubectl -o ${BIN_PATH}/kubectl
chmod +x ${BIN_PATH}/kubectl
