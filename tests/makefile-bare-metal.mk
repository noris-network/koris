.PHONY: create-volumes integration-test-bare-metal

IMAGE ?= noris-CentOS7\ [NorisRapidDeploy]

create-volumes:
	for host in {1..3}; do \
	openstack volume create --size 25 --bootable --availability-zone de-nbg6-1a --type PI-Storage-Class --image $(IMAGE) root-$${host}; done

integration-test-bare-metal: SUBNET ?=sub-korispipeline-office-net
integration-test-bare-metal: ## simulate installation on bare metal
	openstack loadbalancer create --vip-subnet-id $(SUBNET) --name bare-metal
	openstack server create --min 3 --max 3 --wait --flavor ECS.GP1.2-8 --image noris-CentOS7\ [NorisRapidDeploy] test-bare-metal
	openstack loadbalancer delete --cascade --name bare-metal
