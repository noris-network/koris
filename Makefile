SHELL := /bin/bash
.PHONY: clean clean-test clean-pyc clean-build docs help integration-patch-wait \
	clean-lb-after-integration-test clean-lb

.DEFAULT_GOAL := help

ndef = $(if $(value $(1)),,$(error $(1) not set))

define BROWSER_PYSCRIPT
import os, webbrowser, sys

try:
	from urllib import pathname2url
except:
	from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT


PY ?= python3
REV ?= HEAD
BUILD_SUFFIX := $(shell ${PY} -c 'import os;val=os.getenv("CI_PIPELINE_ID");print("-"+val) if val else print("")')
REV_NUMBER = $(shell git rev-parse --short ${REV})
CLUSTER_NAME = koris-pipeline-$(REV_NUMBER)$(BUILD_SUFFIX)
KUBECONFIG ?= $(CLUSTER_NAME)-admin.conf
CIDR ?= 192.168.1.0\/16

BROWSER := $(PY) -c "$$BROWSER_PYSCRIPT"

SONOBUOY_URL = https://github.com/heptio/sonobuoy/releases/download/v0.13.0/sonobuoy_0.13.0_linux_amd64.tar.gz
SONOBUOY_COMPLETED_INDICATOR = "Sonobuoy has completed"
SONOBUOY_CHECK_TIMEOUT_SECONDS = 14400
CIS_VERSION=1.11

help:
	@$(PY) -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test and coverage artifacts
	rm -fr .tox/
	rm -f .coverage
	rm -f .coverage.*
	rm -fr htmlcov/
	rm -fr .pytest_cache

lint: pylint flake8  ## check style with pylint and flake8

pylint: ## check style with pylint
	pylint --rcfile=.pylintrc koris

flake8: ## check style with flake8
	flake8 koris tests

test: test-python test-bash

test-python: ## run tests quickly with the default Python
	@echo "Running Python Unit tests ..."
	py.test

test-bash:
	@echo "Checking bash script syntax ..."
	find koris/provision/userdata/ -name "*.sh" -print0 | xargs -0 -n1 bash -n

coverage: ## check code coverage quickly with the default Python
	$(PY) -m pytest -vv --cov .
	#coverage report -m
	#coverage html
	#$(BROWSER) htmlcov/index.html

rename-coverage: NAME ?= ".coverage.default"
rename-coverage:
	mv .coverage .coverage.$(NAME)

docs: ## generate Sphinx HTML documentation, including API docs
	sphinx-apidoc -o docs/ koris
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	$(BROWSER) docs/_build/html/index.html

docker-alpine:
	docker build -t $(ORG)/koris-alpine:$(TAG) -f docker/Dockerfile.alpine .

docker-ubuntu:
	docker build -t $(ORG)/koris-ubuntu:$(TAG) -f docker/Dockerfile.ubuntu .

docker-push-alpine:
	docker push $(ORG)/koris-alpine:$(TAG)

docker-push-ubuntu:
	docker push $(ORG)/koris-ubuntu:$(TAG)

docker-build-pyinstaller:
	docker build -t $(ORG)/koris-builder:$(TAG) -f docker/Docker-pyinstaller-builder .


servedocs: docs ## compile the docs watching for changes
	watchmedo shell-command -p '*.rst' -c '$(MAKE) -C docs html' -R -D .

release: dist ## package and upload a release
	twine upload dist/*

dist: ## builds source and wheel package
	$(PY) setup.py sdist
	$(PY) setup.py bdist_wheel

install: clean ## install the package to the active Python's site-packages
	$(PY) setup.py install

integration-test: ## run the complete integration test from you local machine
integration-test: \
	reset-config \
	launch-cluster \
	add-nodes \
	add-master \
	integration-run \
	integration-wait \
	integration-patch-wait \
	integration-patch \
	integration-expose \
	expose-wait \
	curl-run \
	check-cluster-dns \
	clean-lb-after-integration-test


compliance-test: ## run the complete compliance test from your local machine
compliance-test: \
	reset-config \
	launch-cluster \
	compliance-checks \
	clean-cluster

launch-cluster: KEY ?= kube  ## launch a cluster with KEY=your_ssh_keypair
launch-cluster: update-config
	$(PY) -m coverage run -m koris -v debug apply tests/koris_test.yml

add-nodes: FLAVOR ?= ECS.UC1.4-4
add-nodes: NUM ?= 2
add-nodes:
	KUBECONFIG=${KUBECONFIG} $(PY) -m coverage run -m koris -v debug add --amount $(NUM) --zone de-nbg6-1a --flavor $(FLAVOR) tests/koris_test.yml
	# wait for the 2 nodes to join.
	# assert cluster has now 5 nodes
	echo "waiting for nodes to join"; \
	until [ $$(kubectl get nodes --kubeconfig=${KUBECONFIG} | grep node | grep Ready -c ) -eq 5 ]; do \
		echo -n "."; \
		sleep 1; \
	done
	@mv tests/koris_test.updated.yml tests/koris_test.add_node.yml
	@echo "OK"

assert-node: NUM ?= 4
assert-node: NODE_TYPE ?= node
assert-node: ACTION ?= labels
assert-node:
	NODE_NAME=$(CLUSTER_NAME)-$(NODE_TYPE)-$(NUM) \
		KUBECONFIG=${KUBECONFIG} \
		tests/scripts/assert_node.sh $(ACTION)

delete-node: NUM ?= 4
delete-node: NODE_TYPE ?= node
delete-node: KORIS_CONF ?= tests/koris_test
delete-node:
	KUBECONFIG=${KUBECONFIG} $(PY) -m coverage run -m koris -v debug delete node --name $(CLUSTER_NAME)-$(NODE_TYPE)-$(NUM) ${KORIS_CONF}.yml
	mv ${KORIS_CONF}.updated.yml tests/koris_test.delete_$(NODE_TYPE).yml

add-master: FLAVOR ?= ECS.UC1.4-4
add-master: KORIS_CONF ?= tests/koris_test
add-master:
	KUBECONFIG=${KUBECONFIG} $(PY) -m coverage run -m koris -v debug add --role master --zone de-nbg6-1a --flavor $(FLAVOR) $(KORIS_CONF).yml
	# wait for the master to join.
	@echo "OK"
	@mv $(KORIS_CONF).updated.yml tests/koris_test.add_master.yml

assert-masters: NUM ?= 4
assert-masters:  ##
	if [ $$(kubectl get nodes --kubeconfig=${KUBECONFIG} -l node-role.kubernetes.io/master -o name | grep -c master) -ne $(NUM) ]; then echo "can't find $(NUM) masters"exit 1; else echo "all masters are fine"; fi

assert-control-plane: NUM ?= 4
assert-control-plane: \
	assert-kube-apiservers \
	assert-etcd \
	assert-kube-controller-manager \
	assert-kube-scheduler

assert-kube-apiservers: NUM ?= 4
assert-kube-apiservers:
	NUM=$(NUM) \
	NAMESPACE="kube-system" \
	KUBECONFIG=${KUBECONFIG} \
	CLUSTER_NAME=$(CLUSTER_NAME) \
	POD_NAME="kube-apiserver" \
	./tests/scripts/assert_pod.sh

assert-etcd: NUM ?= 4
assert-etcd:
	NUM=$(NUM) \
	NAMESPACE="kube-system" \
	KUBECONFIG=${KUBECONFIG} \
	CLUSTER_NAME=$(CLUSTER_NAME) \
	POD_NAME="etcd" \
	./tests/scripts/assert_pod.sh

assert-kube-controller-manager: NUM ?= 4
assert-kube-controller-manager:
	NUM=$(NUM) \
	NAMESPACE="kube-system" \
	KUBECONFIG=${KUBECONFIG} \
	CLUSTER_NAME=$(CLUSTER_NAME) \
	POD_NAME="kube-controller-manager" \
	./tests/scripts/assert_pod.sh

assert-kube-scheduler: NUM ?= 4
assert-kube-scheduler:
	NUM=$(NUM) \
	NAMESPACE="kube-system" \
	KUBECONFIG=${KUBECONFIG} \
	CLUSTER_NAME=$(CLUSTER_NAME) \
	POD_NAME="kube-scheduler" \
	./tests/scripts/assert_pod.sh

assert-members: NUM ?= 4
assert-members:
	./tests/scripts/assert_members.sh $(NUM) $(CLUSTER_NAME)

show-nodes:
	@echo "Waiting for nodes to join ..."
	for i in `seq 1 5`; do \
		sleep 1; \
		kubectl get nodes -o wide --kubeconfig=${KUBECONFIG} | grep -v "No resources found."; \
	done

integration-run:
	kubectl apply -f tests/integration/nginx-pod.yml --kubeconfig=${KUBECONFIG}
	# wait for the pod to be available
	@echo "started"


integration-wait:
	@until kubectl describe pod nginx --kubeconfig=${KUBECONFIG} > /dev/null; \
		do \
	        echo "Waiting for container...." ;\
		sleep 2; \
		done

	@echo "The pod is scheduled"


integration-patch-wait:
	@echo "Waiting for pod status == Running "
	@STATUS=`kubectl get pod --selector=app=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`; \
	while true; do \
		if [ "Running" == "$${STATUS}" ]; then \
			break; \
		fi; \
		STATUS=`kubectl get pod --selector=app=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`;\
		sleep 1; \
		echo -n "."; \
	done ; \


integration-patch:
	@kubectl patch deployment nginx-deployment -p \
		'{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer":"true"}}}}}' \
		--kubeconfig=${KUBECONFIG}

integration-expose:
	@kubectl --kubeconfig=${KUBECONFIG} delete svc nginx-deployment 2>/dev/null || echo "No such service"
	@kubectl expose deployment nginx-deployment --type=LoadBalancer --kubeconfig=${KUBECONFIG}


expose-wait:
	@echo "Waiting for loadBalancer to get an IP"
	@while true; do \
		IP=`kubectl get service nginx-deployment --kubeconfig=${KUBECONFIG} -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`; \
		if [ ! -z $${IP} ]; then \
			break; \
		fi; \
		echo -n "."; \
		sleep 1; \
	done;
	@echo
	@echo "Got an IP!"


reset-config:
	git checkout tests/koris_test.yml

curl-run: IP := $(shell kubectl get service nginx-deployment --kubeconfig=${KUBECONFIG} -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
curl-run:
	@echo "Loadbalancer IP:" $(IP);
	@echo "Waiting for service to become available:"
	@until curl -s http://$(IP):80; do echo -n "."; sleep 1; done;

check-cluster-dns:
	./tests/scripts/test-cluster-dns.sh $(KUBECONFIG)

clean-lb-after-integration-test:
	@kubectl describe service nginx-deployment --kubeconfig=${KUBECONFIG};
	@kubectl delete service nginx-deployment --kubeconfig=${KUBECONFIG}
	# wait for deletion of LB by kubernetes
	@sleep 60

# to delete a loadbalancer the environment variable LOADBALANCER_NAME needs to
# be set to the cluster's name. For example, if one want to delete the
# loadbalancer koris-pipe-line-6e754fe-7008-lb one would need to set
# LOADBALANCER_NAME to koris-pipe-line-6e754fe-7008 (without the -lb)
clean-lb: ## delete a loadbalancer with all it's components
	$(call ndef,LOADBALANCER_NAME)
	LOADBALANCER_NAME=$(LOADBALANCER_NAME) $(PY) tests/scripts/load_balacer_create_and_destroy.py destroy

security-checks: security-checks-nodes security-checks-masters ## run the complete aquasec security tests from your local machine

security-checks-masters: OVERRIDES="{ \"apiVersion\": \"v1\", \
	\"spec\": { \"hostPID\": true, \"nodeSelector\": \
	{ \"node-role.kubernetes.io/master\": \"\" }, \
	\"tolerations\": [ { \"key\": \"node-role.kubernetes.io/master\", \
	                  \"operator\": \"Exists\", \"effect\": \"NoSchedule\" } ] } }"
security-checks-masters:
	@echo "Running security checks for K8S master nodes..."
	@kubectl run --kubeconfig=${KUBECONFIG} kube-bench-master \
		--image=aquasec/kube-bench:latest --restart=Never \
		--overrides=$(OVERRIDES) -- master --version ${CIS_VERSION}
	@sleep 30
	@kubectl logs kube-bench-master --kubeconfig=${KUBECONFIG}

security-checks-nodes:
	@echo "Running security checks for K8S worker nodes..."
	@kubectl run --kubeconfig=${KUBECONFIG} kube-bench-node --image=aquasec/kube-bench:latest --restart=Never \
		--overrides="{ \"apiVersion\": \"v1\", \"spec\": { \"hostPID\": true } }" -- node --version ${CIS_VERSION}
	@sleep 30
	@kubectl logs kube-bench-node --kubeconfig=${KUBECONFIG}

update-config: KEY ?= kube  ## create a test configuration file
update-config: IMAGE ?= $(shell openstack image list -c Name -f value --sort name:desc | grep 'koris-[[:digit:]]' | head -n 1)
update-config:
	@sed -i "s/%%CLUSTER_NAME%%/$(CLUSTER_NAME)/g" tests/koris_test.yml
	@sed -i "s/%%LATEST_IMAGE%%/$(IMAGE)/g" tests/koris_test.yml
	@sed -i "s/keypair: 'kube'/keypair: ${KEY}/g" tests/koris_test.yml
	@cat tests/koris_test.yml

clean-cluster: update-config
	$(PY) -m coverage run -m koris -v debug destroy tests/koris_test.yml --force

clean-all:
	@if [ -r tests/koris_test.updated.yml ]; then \
		mv -v tests/koris_test.updated.yml tests/koris_test.yml; \
		if [ -r tests/koris_test.master.yml ]; then \
			sed -i 's/n-masters:\ 3/n-masters:\ 4/' tests/koris_test.yml; \
		fi; \
	else \
		$(MAKE) reset-config update-config; \
	fi
	$(PY) -m coverage run -m koris -v debug destroy tests/koris_test.yml --force
	@git checkout tests/koris_test.yml
	@rm -fv ${KUBECONFIG}
	@rm -vfR certs-${CLUSTER_NAME}

clean-network-ports:  ## remove dangling ports in Openstack
	openstack port delete $$(openstack port list -f value -c id -c status | grep DOWN | cut -f 1 -d" " | xargs)

check-sonobuoy:
	SONOBUOY_URL=$(SONOBUOY_URL) KUBECONFIG=$(KUBECONFIG) SONOBUOY_CHECK_TIMEOUT_SECONDS=$(SONOBUOY_CHECK_TIMEOUT_SECONDS) \
	SONOBUOY_COMPLETED_INDICATOR=$(SONOBUOY_COMPLETED_INDICATOR) ./tests/scripts/sonobuoy.sh

clean-sonobuoy:
	./sonobuoy --kubeconfig ${KUBECONFIG} delete;
	rm sonobuoy.tgz || true;
	rm sonobuoy || true;

compliance-checks: check-sonobuoy clean-sonobuoy ## run the complete sonobuoy test from your local machine

install-git-hooks:
	pip install git-pylint-commit-hook
	echo "#!/usr/bin/env bash" > .git/hooks/pre-commit
	echo "git-pylint-commit-hook" >> .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit

build-exec: ## build a single file executable of koris
	pyinstaller koris.spec

build-exec-in-docker:
	docker run --rm -v $(PWD):/usr/src/ $(ORG)/koris-builder:$(TAG)

start-release:
	make -f release.mk $@  # $@ is the name of the target

complete-release:
	make -f release.mk do-release
	sleep 2 # this is required because if we don't wait, GL api will miss running jobs
	make -f release.mk abort-pipeline
	make -f release.mk finish-release
	sleep 2 # this is required because if we don't wait, GL api will miss running jobs
	make -f release.mk abort-pipeline


abort-release:
	make -f release.mk $@

# vim: tabstop=4 shiftwidth=4
