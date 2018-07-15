text/x-shellscript
#!/bin/sh
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# Specify the Kubernetes version to use.

# can only use docker 17.03.X
# https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG-1.10.md

apt-get update
apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb https://download.docker.com/linux/$(. /etc/os-release; echo "$ID") $(lsb_release -cs) stable"
apt-get update && apt-get install -y docker-ce=$(apt-cache madison docker-ce | grep 17.03 | head -1 | awk '{print $3}')

K8S_VERSION=v1.10.4
OS=linux
ARCH=amd64


sudo apt-get -y install socat conntrack ipset

K8S_URL=https://storage.googleapis.com/kubernetes-release/release
BIN_PATH=/usr/bin

for item in kubelet kube-proxy; do
    curl ${K8S_URL}/${K8S_VERSION}/bin/${OS}/${ARCH}/${item} -o ${BIN_PATH}/${item}
    chmod -v +x ${BIN_PATH}/${item}
done


# write kubelet.service

# write /etc/systemd/system/kube-proxy.service
