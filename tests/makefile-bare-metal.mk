.PHONY: all create-volumes-masters create-volumes-nodes koris.env

IMAGE ?= "CentOS 7 GenericCloud"
KEY ?= kube
NETWORK ?= korispipeline-office-net
FLAVOR ?= ECS.GP1.2-8
AZ ?= de-nbg6-1a
SECGROUP ?= default
SHELL=/bin/bash
CLUSTERNAME ?= bare-metal
USER ?= centos
USERDATA ?= $(dir $(lastword $(MAKEFILE_LIST)))scripts/fix-ssh-centos.sh

create-volumes-masters:
	@echo "creating volumes for masters"
	for host in {1..3}; do \
	openstack volume create --size 25 --bootable --availability-zone $(AZ) --type PI-Storage-Class --image $(IMAGE) $(CLUSTERNAME)-root-master-$${host}; done

create-volumes-nodes:
	@echo "creating volumes for nodes"
	@openstack volume create --size 25 --bootable --availability-zone $(AZ) --type PI-Storage-Class --image $(IMAGE) $(CLUSTERNAME)-root-node-1


create-masters: #create-volumes-masters
	for host in {1..3}; do \
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume $(CLUSTERNAME)-root-master-$${host} \
		$(CLUSTERNAME)-master-$${host}; \
		--user-data $(dir $(lastword $(MAKEFILE_LIST)))scripts/fix-ssh-centos.sh \
	done

create-nodes: create-volumes-nodes
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume bare-metal-root-node-1 bare-metal-node-1;

integration-test-bare-metal: SUBNET ?=sub-korispipeline-office-net
integration-test-bare-metal: create-volumes-masters create-volumes-nodes creates-masters create-nodes ## simulate installation on bare metal
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name bare-metal

create-loadbalancer: SUBNET ?=sub-korispipeline-office-net
create-loadbalancer:
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name bare-metal


config-loadbalancer: FIRSTMASTER ?= bare-metal-master-1
config-loadbalancer:
	@echo "Waiting for loadbalancer to become ACTIVE"
	until openstack loadbalancer show bare-metal -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer listener create --name "bare-metal-lb-listener" --protocol TCP --protocol-port 6443 bare-metal
	until openstack loadbalancer show bare-metal -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer pool create --name bare-metal-pool --protocol TCP --listener bare-metal-lb-listener --lb-algorithm SOURCE_IP
	until openstack loadbalancer show bare-metal -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer member create --address $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=") --protocol-port 6443 bare-metal-pool

add-master-to-lb: FIRSTMASTER ?= bare-metal-master-1
add-master-to-lb:
	until openstack loadbalancer show bare-metal -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer member create --address $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=") --protocol-port 6443 bare-metal-pool


koris.env: FIRSTMASTER ?= bare-metal-master-1
koris.env: .SHELLFLAGS = -c eval
koris.env: SHELL = bash -c 'eval "$${@//\\\\/}"'
koris.env:
	@cat <<-EOF > koris.env \
	export BOOTSTRAP_NODES=1 \
	export POD_SUBNET="10.233.0.0/16" \
	export POD_NETWORK="CALICO" \
	export LOAD_BALANCER_PORT="6443" \
	EOF
	HOSTS=(); \
	IPS=(); \
	while read line; do \
	IPS+=( $$(echo $$line | cut -d"=" -f 2) ); \
	HOSTS+=( $$(echo $$line | cut -d" " -f 1) ); \
	done < <( openstack server list --name $(CLUSTERNAME) -f value -c Name -c Networks | sort ); \
	echo "export MASTERS_IPS=( $${IPS[@]} )" >> koris.env \
	echo "export MASTERS=( $${HOSTS[@]} )" >> koris.env \
	echo "export LOAD_BALANCER_IP="$$(openstack loadbalancer show bare-metal -f value -c vip_address)"" >> koris.env
	echo "export BOOTSTRAP_TOKEN=$$(openssl rand -hex 3).$$(openssl rand -hex 8)" >> koris.env
	echo "export OPENSTACK=0" >> koris.env
	echo "export SSH_USER=$(USER)" >> koris.env


cp-koris-env: FIRSTMASTER ?= bare-metal-master-1
cp-koris-env: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
cp-koris-env:
	@echo $(FIRSTMASTER_IP)
	ssh $(USER)@$(FIRSTMASTER_IP) sudo mkdir -pv /etc/kubernetes/
	cat koris.env | ssh $(USER)@$(FIRSTMASTER_IP) "sudo sh -c 'cat >/etc/kubernetes/koris.env'"

cp-bootstrap-script: FIRSTMASTER ?= bare-metal-master-1
cp-bootstrap-script: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
cp-bootstrap-script:
	scp -r koris/provision/userdata/bootstrap-k8s-master-ubuntu-16.04.sh centos@$(FIRSTMASTER_IP):~

run-bootstrap: FIRSTMASTER ?= bare-metal-master-1
run-bootstrap: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
run-bootstrap:
	ssh -A $(USER)@$(FIRSTMASTER_IP) sudo bash bootstrap-k8s-master-ubuntu-16.04.sh

clean-lb:
	openstack loadbalancer delete bare-metal --cascade

clean-instances:
	for host in {1..3}; do openstack server delete bare-metal-master-$${host}; done
	#openstack server delete bare-metal-node-1

clean-volumes:
	for host in {1..3}; do openstack volume delete bare-metal-root-master-$${host}; done
	#openstack volume delete bare-metal-root-node-1

clean: clean-instances clean-volumes clean-lb

bootstrap: create-volumes-masters create-masters create-loadbalancer koris.env cp-koris-env cp-bootstrap-script run-bootstrap

integration-test: create-volumes-masters create-volumes-nodes create-masters create-nodes create-loadbalancer clean ## simulate installation on bare metal
