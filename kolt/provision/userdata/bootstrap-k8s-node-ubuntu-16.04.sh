text/x-shellscript
#!/bin/bash
# --------------------------------------------------------------------------------------------------------------
# We are explicitly not using a templating language to inject the values as to encourage the user to limit their
# set of templating logic in these files. By design all injected values should be able to be set at runtime,
# and the shell script real work. If you need conditional logic, write it in bash or make another shell script.
# --------------------------------------------------------------------------------------------------------------

# ONLY CHANGE VERSIONS HERE IF YOU KNOW WHAT YOU ARE DOING!
# MAKE SURE THIS MATCHED THE MASTER K8S VERSION
KUBE_VERSION="1.12.2"
#KUBE_VERSION="1.11.4"

sudo apt-get update
sudo apt-get install -y software-properties-common
sudo swapoff -a
sudo curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
sudo apt-add-repository -u "deb http://apt.kubernetes.io kubernetes-xenial main"
sudo apt install -y --allow-downgrades kubeadm=${KUBE_VERSION}-00 \
	kubelet=${KUBE_VERSION}-00 kubectl=${KUBE_VERSION}-00

sudo "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -"
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
sudo apt-get update
sudo apt-get -y install docker-ce

sudo mkdir -p /etc/kubernetes/pki/etcd
iptables -P FORWARD ACCEPT

cat << EOF > /etc/kubernetes/cluster-info.yaml
---
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUN5RENDQWJDZ0F3SUJBZ0lCQURBTkJna3Foa2lHOXcwQkFRc0ZBREFWTVJNd0VRWURWUVFERXdwcmRXSmwKY201bGRHVnpNQjRYRFRFNE1URXdNekEwTlRrME4xb1hEVEk0TVRBek1UQTBOVGswTjFvd0ZURVRNQkVHQTFVRQpBeE1LYTNWaVpYSnVaWFJsY3pDQ0FTSXdEUVlKS29aSWh2Y05BUUVCQlFBRGdnRVBBRENDQVFvQ2dnRUJBTU9BCkNHQU5jUjVRQWV3MlljY2V0eWVyYktiODd4RWRPVlp2aUdneElrbkpKTTZwZFVBbzMwSWVxckRqSnlFaTFVeDcKU0c5NS9sRlBqU1htdHhhNHMvc1g1KzNTVW4zZEtFRWw5TFhXa0lzeTRJYzRFUTMwWE9WcnNuYTYwN1UzNmQyaAp3NHdTK1dveE5QR3dqZDM2bXQzMFR4bUluYk54ZVl5d2NnVU1tMlZFZXM4dGhVaVhZMXB1N1Y2SUNCY243cE9NCkdoT2xlRXg4SmlEVnhuSGlpSm9oYytCbGNIdHdLU1pzK2cvZUhwdGdlSDdaQlZNRC8zZVFvZXVsUGVvTEkwamEKc09jTENMTkpEVVBLUWJqRnRNbkFZSXVvOENHSXpFTzBDaDZNeW5vb1pTL0E0bEs1MXJmTVdkTkZ4N0dVdnQxYQo5KzZzMHo2NEpHeVFBdmtBcWhVQ0F3RUFBYU1qTUNFd0RnWURWUjBQQVFIL0JBUURBZ0trTUE4R0ExVWRFd0VCCi93UUZNQU1CQWY4d0RRWUpLb1pJaHZjTkFRRUxCUUFEZ2dFQkFEbWs1NEYzZ1BqOS91NzlRbTg2V1Mzck5YaFoKZG16Wmt3TXRDajRuTXdsSndGQy9iZUU4ZUdsWnFxWDcrdEpYUDVaY0xLNE1pSnM1U2JTMjd5NDF3WTRRTFFWaQpVWmRocEFHUTBOSlpHSGhWMTVDczlVQTA1ZTFNajNCaHZ6SG5VV2t1ZUhYbW84VmI4SkI5RGloeGdiUW5GY2FQCjRWcVhWY0pBemxVQ0V5aXhreVRGendZTklJbzJHdGtCdlI1YkxCM0doT2RsQURmQzEwdzgvTmQveFFmRnRWdmYKL3lHaktpbW8rT2xERkV5YittcHVKMVdiN3Y3bnJJSzlSSy9WbVhUWENiOWZLQ3BmQ0hMU0hpa0lEWklZK0wxTQpwbWpXYXZFcjFLSlE5UEJIYmdZSHkxK1F0bkpXRDNjNnJrOUtoNU1zMFhTVmpBc2Z1RWdXaG9CYnlVdz0KLS0tLS1FTkQgQ0VSVElGSUNBVEUtLS0tLQo=
    server: https://k8s.oz.noris.de:6443
  name: ""
contexts: []
current-context: ""
kind: Config
preferences: {}
users: []
EOF

# config for 1.11.4
cat << EOF > /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml
apiVersion: kubeadm.k8s.io/v1alpha1
kind: NodeConfiguration
discoveryFile: /etc/kubernetes/cluster-info.yaml
nodeName: node-1-test2
tlsBootstrapToken: foobar.fedcba9876543210
discoveryTokenCACertHashes:
  sha256:fe3c078b230624ec2297133933314b9a2821fa12c80226957ea716546d0cc1a9
EOF

# config for 1.12.2
cat << EOF > /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml
---
apiVersion: kubeadm.k8s.io/v1alpha2
clusterName: kubernetes
discoveryFile: /etc/kubernetes/cluster-info.yaml
discoveryTimeout: 15m0s
discoveryTokenUnsafeSkipCAVerification: true
kind: NodeConfiguration
nodeRegistration:
  criSocket: /var/run/dockershim.sock
  name: node-1-test2
tlsBootstrapToken: foobar.fedcba9876543210
EOF

# join !
kubeadm -v=10 join --config /etc/kubernetes/kubeadm-node-${KUBE_VERSION}.yaml k8s.oz.noris.de:6443
