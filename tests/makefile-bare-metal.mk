.PHONY: all create-volumes-masters create-volumes-nodes

IMAGE ?= noris-CentOS7\ [NorisRapidDeploy]
KEY ?= kube
NETWORK ?= korispipeline-office-net
FLAVOR ?= ECS.GP1.2-8
AZ ?= de-nbg6-1a
SECGROUP ?= default

create-volumes-masters:
	@echo "creating volumes for masters"
	@for host in {1..3}; do \
	openstack volume create --size 25 --bootable --availability-zone $(AZ) --type PI-Storage-Class --image $(IMAGE) root-master-$${host}; done

create-volumes-nodes:
	@echo "creating volumes for nodes"
	@openstack volume create --size 25 --bootable --availability-zone $(AZ) --type PI-Storage-Class --image $(IMAGE) root-node-1


create-masters: create-volumes-masters
	for host in {1..3}; do \
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume root-master-$${host} master-$${host}; \
	done

create-nodes: create-volumes-nodes
	openstack server create --network $(NETWORK) --flavor $(FLAVOR) --availability-zone $(AZ) --key-name $(KEY) \
		--security-group $(SECGROUP) --volume root-node-1 node-1;

integration-test-bare-metal: SUBNET ?=sub-korispipeline-office-net
integration-test-bare-metal: create-volumes-masters create-volumes-nodes creates-masters create-nodes ## simulate installation on bare metal
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name bare-metal


create-loadbalancer: SUBNET ?=sub-korispipeline-office-net
create-loadbalancer:
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name bare-metal

clean-lb:
	openstack loadbalancer delete --cascade bare-metal

clean-instances:
	for host in {1..3}; do openstack server delete master-$${host}; done
	openstack server delete node-1

clean-volumes:
	for host in {1..3}; do openstack volume delete root-master-$${host}; done
	openstack volume delete root-node-1

clean: clean-instances clean-lb

integration-test: create-volumes-masters create-volumes-nodes create-masters create-nodes create-loadbalancer clean ## simulate installation on bare metal
