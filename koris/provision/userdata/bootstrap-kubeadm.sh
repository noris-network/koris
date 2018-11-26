#!/bin/bash

###
# A script to create a HA K8S cluster on OpenStack using pure bash and kubeadm
###

# begin openstack machine logic ...

declare -A MASTERS
declare -A HOSTS
# HOSTS contain a name -> availability zone

MASTERS["master-1-a"]="de-nbg6-1a"
MASTERS["master-2-a"]="de-nbg6-1a"
MASTERS["master-3-b"]="de-nbg6-1b"

HOSTS["worker-1-a"]="de-nbg6-1a"
HOSTS["worker-2-a"]="de-nbg6-1a"
HOSTS["worker-3-a"]="de-nbg6-1a"

HOSTS["worker-4-b"]="de-nbg6-1b"
HOSTS["worker-5-b"]="de-nbg6-1b"
HOSTS["worker-6-b"]="de-nbg6-1b"

IMAGE=koris-2018-11-24
MASTER_FLAVOR=ECS.C1.2-4
WORKER_FLAVOR=ECS.C1.4-8
####
# these two variables will eventually be dropped.
####
SUBNET="k8s-subnet"
FLOATING_IP="213.95.155.150"


# create volumes:
for K in "${!HOSTS[@]}"; do
	openstack volume create --size 25 --bootable --availability-zone ${HOSTS[$K]} --type PI-Storage-Class --image $IMAGE root-${K}
done
for K in "${!MASTERS[@]}"; do
	openstack volume create --size 25 --bootable --availability-zone ${MASTERS[$K]} --type PI-Storage-Class --image $IMAGE root-${K}
done

# create masters servers
for K in "${!MASTERS[@]}"; do
	openstack server create --network k8s-network --flavor ${MASTER_FLAVOR} --availability-zone ${MASTERS[$K]} --key-name otiram --security-group k8s-default --volume root-${K} ${K}
done

# create worker nodes
for K in "${!HOSTS[@]}"; do
	openstack server create --network k8s-network --flavor ${WORKER_FLAVOR} --availability-zone ${HOSTS[$K]} --key-name otiram --security-group k8s-default --volume root-${K} ${K}
done


SUBNET_ID=$(neutron subnet-show k8s-subnet -f value -c id)
MASTER1_IP=$(openstack server show master-1-a -f value -c addresses | cut -d"=" -f 2)
MASTER2_IP=$(openstack server show master-2-a -f value -c addresses | cut -d"=" -f 2)
MASTER3_IP=$(openstack server show master-3-b -f value -c addresses | cut -d"=" -f 2)

## create load balancer
neutron lbaas-loadbalancer-create --name k8s-ha ${SUBNET}
while [[ "PENDING_CREATE" == $(neutron lbaas-loadbalancer-show k8s-ha -f value -c provisioning_status) ]];
   do sleep 4;
done
## add listener for kube-api-server
neutron lbaas-listener-create --loadbalancer k8s-ha --name k8s-ha-listener --protocol TCP --protocol-port 6443

LISTENER_ID=$(neutron lbaas-listener-show k8s-ha-listener -f value -c id)
while [[ "PENDING_UPDATE" == $(neutron lbaas-loadbalancer-show k8s-ha -f value -c provisioning_status) ]];
   do sleep 2;
done

## add pool, this is not HTTP but HTTPS, hence we use TCP
neutron lbaas-pool-create --name k8s-ha-pool --listener k8s-ha-listener --protocol TCP --lb-algorithm ROUND_ROBIN
POOL_ID=$(neutron lbaas-pool-show k8s-ha-pool -c id -f value)

## add member
neutron lbaas-member-create --subnet ${SUBNET} --address $MASTER1_IP --protocol-port 6443  $POOL_ID
sleep 4
neutron lbaas-member-create --subnet ${SUBNET} --address $MASTER2_IP --protocol-port 6443  $POOL_ID
sleep 4
neutron lbaas-member-create --subnet ${SUBNET} --address $MASTER3_IP --protocol-port 6443  $POOL_ID

## add listener for ssh
neutron lbaas-listener-create --loadbalancer k8s-ha --name k8s-ssh-1 --protocol TCP --protocol-port 2122
while [[ "PENDING_UPDATE" == $(neutron lbaas-loadbalancer-show k8s-ssh-1 -f value -c provisioning_status) ]];
   do sleep 2;
done

# add SSH pools
neutron lbaas-pool-create --name k8s-ssh-pool-1 --listener k8s-ssh-host-1 --protocol TCP --lb-algorithm ROUND_ROBIN
POOL_ID=$(neutron lbaas-pool-show k8s-ssh-pool-1 -c id -f value)
neutron lbaas-member-create --subnet ${SUBNET} --address $MASTER1_IP --protocol-port 22  $POOL_ID

VIP_PORT_ID=$(neutron lbaas-loadbalancer-show k8s-ha  -c vip_port_id -f value)

export VIP_PORT_ID

FIP_ID=$(neutron  floatingip-list -f value | grep ${FLOATING_IP} | cut -d" " -f 1)
neutron floatingip-associate $FIP_ID $VIP_PORT_ID

### end openstack machine logic - until here everything is already implemented in
### the current koris code base in Python


ALLHOSTS=( "${!HOSTS[@]}" "${!MASTERS[@]}" )

for host in  "${ALLHOSTS[@]}"; do ssh-copy-id -o 'StrictHostKeyChecking=no' -i ~/.ssh/id_rsa.pub $host; done

for K in "${ALLHOSTS[@]}"; do
	ssh ${K} sudo apt-get update
	ssh ${K} sudo apt-get install -y software-properties-common
        ssh ${K} sudo swapoff -a
	ssh ${K} "curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -"
	ssh ${K} "sudo apt-add-repository -u \"deb http://apt.kubernetes.io kubernetes-xenial main\""
        ssh ${K} sudo apt install -y --allow-downgrades kubeadm=1.11.4-00 kubelet=1.11.4-00
done

for K in "${ALLHOSTS[@]}"; do
	ssh ${K} sudo "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -"
	ssh ${K} sudo "add-apt-repository \"deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\""
	ssh ${K} sudo apt-get update
	ssh ${K} sudo apt-get -y install docker-ce
done


cat << EOF > cluster.env
MASTER1_IP=${MASTER1_IP}
MASTER2_IP=${MASTER2_IP}
MASTER3_IP=${MASTER3_IP}
LOAD_BALANCER_IP=${FLOATING_IP}
LOAD_BALANCER_PORT=6443
CP0_IP=$MASTER1_IP
CP1_IP=$MASTER2_IP
CP2_IP=$MASTER3_IP
CP0_HOSTNAME=master-1-a
CP1_HOSTNAME=master-2-a
CP2_HOSTNAME=master-3-b
POD_SUBNET=10.233.0.0/16
KUBE_VERSION=1.11.4
EOF

source cluster.env

cat << EOF > kubeadm-master-1.yaml
apiVersion: kubeadm.k8s.io/v1alpha2
kind: MasterConfiguration
kubernetesVersion: v${KUBE_VERSION}
apiServerCertSANs:
- "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}"
api:
    controlPlaneEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
etcd:
  local:
    extraArgs:
      listen-client-urls: "https://127.0.0.1:2379,https://${CP0_IP}:2379"
      advertise-client-urls: "https://${CP0_IP}:2379"
      listen-peer-urls: "https://${CP0_IP}:2380"
      initial-advertise-peer-urls: "https://${CP0_IP}:2380"
      initial-cluster: "${CP0_HOSTNAME}=https://${CP0_IP}:2380"
    serverCertSANs:
      - ${CP0_HOSTNAME}
      - ${CP0_IP}
    peerCertSANs:
      - ${CP0_HOSTNAME}
      - ${CP0_IP}
networking:
    # This CIDR is a Calico default. Substitute or remove for your CNI provider.
    podSubnet: ${POD_SUBNET}
bootstrapTokens:
- groups:
  - system:bootstrappers:kubeadm:default-node-token
  token: foobar.fedcba9876543210
  ttl: 24h0m0s
  usages:
  - signing
  - authentication
EOF

sudo kubeadm init --config  kubeadm-master-1.yaml

test -d .kube || mkdir .kube
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown ubuntu:ubuntu ~/.kube/config
kubectl get nodes

USER=ubuntu # customizable
CONTROL_PLANE_IPS="master-2-a master-3-b"
for host in ${CONTROL_PLANE_IPS}; do
    ssh ${USER}@$host sudo rm -vRf /etc/kubernetes
    ssh ${USER}@$host mkdir -pv kubernetes/pki/etcd
    sudo -E scp /etc/kubernetes/pki/ca.crt "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/ca.key "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/sa.key "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/sa.pub "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/front-proxy-ca.crt "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/front-proxy-ca.key "${USER}"@$host:~/kubernetes/pki/
    sudo -E scp /etc/kubernetes/pki/etcd/ca.crt "${USER}"@$host:~/kubernetes/pki/etcd/
    sudo -E scp /etc/kubernetes/pki/etcd/ca.key "${USER}"@$host:~/kubernetes/pki/etcd/
    sudo -E scp /etc/kubernetes/admin.conf "${USER}"@$host:~/kubernetes/

    ssh ${USER}@$host sudo mv -v kubernetes /etc/
	ssh ${USER}@$host sudo chown root:root -vR /etc/kubernetes
    ssh ${USER}@$host sudo chmod 0600 -vR /etc/kubernetes/admin.conf
done

cat << EOF > kubeadm-master-2.yaml
apiVersion: kubeadm.k8s.io/v1alpha2
kind: MasterConfiguration
kubernetesVersion: v${KUBE_VERSION}
apiServerCertSANs:
- "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}"
api:
    controlPlaneEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
etcd:
  local:
    extraArgs:
      listen-client-urls: "https://127.0.0.1:2379,https://${CP1_IP}:2379"
      advertise-client-urls: "https://${CP1_IP}:2379"
      listen-peer-urls: "https://${CP1_IP}:2380"
      initial-advertise-peer-urls: "https://${CP1_IP}:2380"
      initial-cluster: "${CP0_HOSTNAME}=https://${CP0_IP}:2380,${CP1_HOSTNAME}=https://${CP1_IP}:2380"
      initial-cluster-state: existing
    serverCertSANs:
      - ${CP1_HOSTNAME}
      - ${CP1_IP}
    peerCertSANs:
      - ${CP1_HOSTNAME}
      - ${CP1_IP}
networking:
    # This CIDR is a calico default. Substitute or remove for your CNI provider.
    podSubnet:  "${POD_SUBNET}"
EOF

scp  kubeadm-master-2.yaml $CP1_HOSTNAME:~/

ssh $CP1_HOSTNAME sudo kubeadm alpha phase certs all --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase kubelet config write-to-disk --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase kubelet write-env-file --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase kubeconfig kubelet --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo systemctl start kubelet


sudo kubectl exec -n kube-system etcd-${CP0_HOSTNAME} -- etcdctl --ca-file /etc/kubernetes/pki/etcd/ca.crt --cert-file /etc/kubernetes/pki/etcd/peer.crt --key-file /etc/kubernetes/pki/etcd/peer.key --endpoints=https://${CP0_IP}:2379 member add ${CP1_HOSTNAME} https://${CP1_IP}:2380

ssh $CP1_HOSTNAME sudo kubeadm alpha phase etcd local --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase kubeconfig all --config  kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase controlplane all --config   kubeadm-master-2.yaml
ssh $CP1_HOSTNAME sudo kubeadm alpha phase mark-master --config  kubeadm-master-2.yaml


cat << EOF > kubeadm-master-3.yaml
apiVersion: kubeadm.k8s.io/v1alpha2
kind: MasterConfiguration
kubernetesVersion: v${KUBE_VERSION}
apiServerCertSANs:
- "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}"
api:
    controlPlaneEndpoint: "${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:${LOAD_BALANCER_PORT}"
etcd:
  local:
    extraArgs:
      listen-client-urls: "https://127.0.0.1:2379,https://${CP2_IP}:2379"
      advertise-client-urls: "https://${CP2_IP}:2379"
      listen-peer-urls: "https://${CP2_IP}:2380"
      initial-advertise-peer-urls: "https://${CP2_IP}:2380"
      initial-cluster: "${CP0_HOSTNAME}=https://${CP0_IP}:2380,${CP1_HOSTNAME}=https://${CP1_IP}:2380,${CP2_HOSTNAME}=https://${CP2_IP}:2380"
      initial-cluster-state: existing
    serverCertSANs:
      - ${CP2_HOSTNAME}
      - ${CP2_IP}
    peerCertSANs:
      - ${CP2_HOSTNAME}
      - ${CP2_IP}
networking:
    # This CIDR is a calico default. Substitute or remove for your CNI provider.
    podSubnet:  "${POD_SUBNET}"
EOF

scp kubeadm-master-3.yaml $CP2_HOSTNAME:~/

ssh $CP2_HOSTNAME sudo kubeadm alpha phase certs all --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase kubelet config write-to-disk --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase kubelet write-env-file --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase kubeconfig kubelet --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo systemctl start kubelet

sudo kubectl exec -n kube-system etcd-${CP0_HOSTNAME} -- etcdctl --ca-file /etc/kubernetes/pki/etcd/ca.crt --cert-file /etc/kubernetes/pki/etcd/peer.crt --key-file /etc/kubernetes/pki/etcd/peer.key --endpoints=https://${CP0_IP}:2379 member add ${CP2_HOSTNAME} https://${CP2_IP}:2380

ssh $CP2_HOSTNAME sudo kubeadm alpha phase etcd local --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase kubeconfig all --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase controlplane all --config kubeadm-master-3.yaml
ssh $CP2_HOSTNAME sudo kubeadm alpha phase mark-master --config kubeadm-master-3.yaml

# add calico!
curl -O https://docs.projectcalico.org/v3.1/getting-started/kubernetes/installation/hosted/rbac-kdd.yaml
curl -O https://docs.projectcalico.org/v3.1/getting-started/kubernetes/installation/hosted/kubernetes-datastore/calico-networking/1.7/calico.yaml

sed "s@192.168.0.0/16@"${POD_SUBNET}"@g" calico.yaml

export DISCOVERY_HASH=$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | \
   openssl dgst -sha256 -hex | sed 's/^.* //')
export TOKEN=$(kubeadm token list | grep -v TOK| cut -d" " -f 1 | grep '^\S')

for K in "${!HOSTS[@]}"; do
    ssh ${K} sudo kubeadm reset -f
    ssh ${K} sudo kubeadm join --token $TOKEN ${LOAD_BALANCER_DNS:-${LOAD_BALANCER_IP}}:$LOAD_BALANCER_PORT --discovery-token-ca-cert-hash sha256:${DISCOVERY_HASH}
done

###
# this is how you ssh directly to all machines over the first master
###

# ssh -tt  -o ProxyCommand='ssh -v -A -i /home/oznt/.ssh/id_rsa.noris ubuntu@<loadbalancer> -p 22 -W [%h]:%p' ubuntu@<node>

