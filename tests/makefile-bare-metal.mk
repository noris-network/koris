.PHONY: all create-volumes-masters create-volumes-nodes koris.env
IMAGE ?= "noris-CentOS7 [NorisRapidDeploy]"
KEY ?= kube
NETWORK ?= korispipeline-office-net
FLAVOR ?= ECS.C1.2-4
AZ ?= de-nbg6-1a
SECGROUP ?= default
SHELL=/bin/bash
CLUSTERNAME ?= bare-metal
USER ?= centos
USERDATA ?= $(dir $(lastword $(MAKEFILE_LIST)))scripts/fix-ssh-centos.sh
SSHOPTS = -o StrictHostKeyChecking=no

create-volumes-masters:
	@echo "creating volumes for masters"
	for host in {1..3}; do \
	openstack volume create --size 25 --bootable --availability-zone $(AZ) --type BSS-Performance-Storage --image $(IMAGE) $(CLUSTERNAME)-root-master-$${host}; done

create-volumes-nodes:
	@echo "creating volumes for nodes"
	openstack volume create --size 25 --bootable --availability-zone $(AZ) --type BSS-Performance-Storage --image $(IMAGE) $(CLUSTERNAME)-root-node-1

create-masters: #create-volumes-masters
	for host in {1..3}; do \
	until openstack volume show $(CLUSTERNAME)-root-master-$${host} -c status -f value | grep available; do sleep 2; done; \
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume $(CLUSTERNAME)-root-master-$${host} \
		$(CLUSTERNAME)-master-$${host} \
		--user-data $(USERDATA); \
	done

create-nodes:
	until openstack volume show $(CLUSTERNAME)-root-node-1 -c status -f value | grep available; do sleep 2; done;  \
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume $(CLUSTERNAME)-root-node-1 \
		--user-data $(USERDATA) \
		$(CLUSTERNAME)-node-1;

create-loadbalancer: SUBNET ?=sub-korispipeline-office-net
create-loadbalancer:
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name $(CLUSTERNAME)


config-loadbalancer: FIRSTMASTER ?= $(CLUSTERNAME)-master-1
config-loadbalancer:
	@echo "Waiting for loadbalancer to become ACTIVE"
	until openstack loadbalancer show $(CLUSTERNAME) -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer listener create --name "$(CLUSTERNAME)-lb-listener" --protocol TCP --protocol-port 6443 $(CLUSTERNAME)
	until openstack loadbalancer show $(CLUSTERNAME) -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer pool create --name $(CLUSTERNAME)-pool --protocol TCP --listener $(CLUSTERNAME)-lb-listener --lb-algorithm SOURCE_IP
	until openstack loadbalancer show $(CLUSTERNAME) -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer member create --address $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=") --protocol-port 6443 $(CLUSTERNAME)-pool

add-master-to-lb: FIRSTMASTER ?= bare-metal-master-1
add-master-to-lb:
	until openstack loadbalancer show $(CLUSTERNAME) -f value -c provisioning_status | grep ACTIVE ; do sleep 2; done
	openstack loadbalancer member create --address $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=") --protocol-port 6443 $(CLUSTERNAME)-pool


koris.env: FIRSTMASTER ?= $(CLUSTERNAME)-master-1
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
	done < <( openstack server list --name $(CLUSTERNAME)-master -f value -c Name -c Networks | sort ); \
	echo "export MASTERS_IPS=( $${IPS[@]} )" >> koris.env \
	echo "export MASTERS=( $${HOSTS[@]} )" >> koris.env \
	echo "export LOAD_BALANCER_IP="$$(openstack loadbalancer show $(CLUSTERNAME) -f value -c vip_address)"" >> koris.env
	echo "export BOOTSTRAP_TOKEN=$$(openssl rand -hex 3).$$(openssl rand -hex 8)" >> koris.env
	echo "export OPENSTACK=0" >> koris.env
	echo "export SSH_USER=$(USER)" >> koris.env
	echo "export K8SNODES=( $(CLUSTERNAME)-node-1 )" >> koris.env
	echo "Bootstrapping with koris.env:"; cat koris.env


cp-koris-env: FIRSTMASTER ?= $(CLUSTERNAME)-master-1
cp-koris-env: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
cp-koris-env:
	@echo $(FIRSTMASTER_IP)
	for i in 1..60; do \
		ssh $(SSHOPTS) $(USER)@$(FIRSTMASTER_IP) sudo mkdir -pv /etc/kubernetes/ && break; \
		sleep 5 ; \
	done
	cat koris.env | ssh $(SSHOPTS) $(USER)@$(FIRSTMASTER_IP) "sudo sh -c 'cat >/etc/kubernetes/koris.env'"

cp-bootstrap-script: FIRSTMASTER ?= $(CLUSTERNAME)-master-1
cp-bootstrap-script: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
cp-bootstrap-script:
	scp $(SSHOPTS) -r koris/provision/userdata/bootstrap-k8s-master-ubuntu-16.04.sh $(USER)@$(FIRSTMASTER_IP):~

run-bootstrap: FIRSTMASTER ?= $(CLUSTERNAME)-master-1
run-bootstrap: FIRSTMASTER_IP ?= $$(openstack server show $(FIRSTMASTER) -f value -c addresses | cut -f 2 -d "=")
run-bootstrap: BOOTSTRAPUSER ?= root
run-bootstrap: OSUSER ?= centos
run-bootstrap:
	ssh $(SSHOPTS) -A $(BOOTSTRAPUSER)@$(FIRSTMASTER_IP) bash /home/$(OSUSER)/bootstrap-k8s-master-ubuntu-16.04.sh

clean-lb:
	openstack loadbalancer delete $(CLUSTERNAME) --cascade || echo "No load balancer foud"

clean-masters:
	for host in {1..3}; do openstack server delete $(CLUSTERNAME)-master-$${host} || echo "No server found " $(CLUSTERNAME)-master-$${host} ; done

clean-nodes:
	openstack server delete $(CLUSTERNAME)-node-1 || exit 0

clean-volumes-masters:
	for host in {1..3}; do \
		openstack volume show $(CLUSTERNAME)-root-master-$${host} -c status -f value || continue; \
		until openstack volume show $(CLUSTERNAME)-root-master-$${host} -c status -f value | grep available; do sleep 2; done; \
		openstack volume delete $(CLUSTERNAME)-root-master-$${host}; done

clean-volumes-nodes:
	openstack volume show $(CLUSTERNAME)-root-node-1 -c status -f value || exit 0; \
	until openstack volume show $(CLUSTERNAME)-root-node-1 -c status -f value | grep available; do sleep 2; done; \
	openstack volume delete $(CLUSTERNAME)-root-node-1

BUILD_TARGETS := create-volumes-masters create-volumes-nodes create-masters create-nodes create-loadbalancer config-loadbalancer
build-cluster-bare-metal: $(BUILD_TARGETS)
	@echo "Finished building a 'bare metal cluster, using Noris Standard image'"

IT_TARGETS += koris.env cp-koris-env cp-bootstrap-script run-bootstrap
integration-test-bare-metal: $(IT_TARGETS)
	@echo "Finished all"
	@echo "Waiting for all nodes to become ready ..."
	@sleep 140
	until [ $$(ssh -A -o StrictHostKeyChecking=no root@$$(openstack server show $(CLUSTERNAME)-master-1 -f value -c addresses | cut -f 2 -d "=") kubectl get nodes | grep -c Ready) -eq 4 ]; do echo "waiting for all nodes to become ready ..."; done


clean-all: clean-lb clean-masters clean-volumes-masters clean-nodes clean-volumes-nodes

assert-audit-policy:
	for idx in {1..3}; do \
		MASTER=$$(openstack server show $(CLUSTERNAME)-master-$${idx} -f value -c addresses | cut -f 2 -d "="); \
		echo "Checking $${CLUSTERNAME}-master-$${idx}"; \
		ssh $(SSHOPTS) -l $(USER) $${MASTER} test -f /var/log/kubernetes; \
		ssh $(SSHOPTS) -l $(USER) $${MASTER} test -f /etc/kubernetes/audit-policy.yml ; \
	done
