SHELL := /bin/bash
.PHONY: clean clean-test clean-pyc clean-build docs help curl-run \
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
PYTEST_FLAGS ?=
REV ?= HEAD
BUILD_SUFFIX := $(shell ${PY} -c 'import os;val=os.getenv("CI_PIPELINE_ID");print("-"+val) if val else print("")')
REV_NUMBER = $(shell git rev-parse --short ${REV})
CLUSTER_NAME ?= koris-pipeline-$(REV_NUMBER)$(BUILD_SUFFIX)
KUBECONFIG ?= $(CLUSTER_NAME)-admin.conf
CIDR ?= 192.168.1.0\/16
CONFIG_FILE ?= tests/koris_test.yml
UBUNTU_VER ?= 16.04
TEST_ID ?= 0

BROWSER := $(PY) -c "$$BROWSER_PYSCRIPT"

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
	py.test $(PYTEST_FLAGS)

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
	curl-run \
	check-cluster-dns \
	clean-lb-after-integration-test

curl-run:
	export KUBECONFIG=$(KUBECONFIG); bash tests/integration/curl-lb.sh

compliance-test: ## run the complete compliance test from your local machine
compliance-test: \
	reset-config \
	launch-cluster \
	compliance-checks \
	clean-cluster

launch-cluster: KEY ?= kube  ## launch a cluster with KEY=your_ssh_keypair
launch-cluster: update-config
	$(PY) -m coverage run -m koris -v debug apply $(CONFIG_FILE)

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
	KUBECONFIG=${KUBECONFIG} $(PY) -m coverage run -m koris -v debug delete node --name $(CLUSTER_NAME)-$(NODE_TYPE)-$(NUM) ${KORIS_CONF}.yml -f
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
	NUM=${NUM} \
	KUBECONFIG=${KUBECONFIG} \
	CLUSTER_NAME=${CLUSTER_NAME} ./tests/scripts/check-joined-master.sh

assert-audit-log: NUM ?= 4
assert-audit-log:
	NUM=${NUM} \
	KUBECONFIG=${KUBECONFIG} CLUSTER_NAME=${CLUSTER_NAME} ./tests/scripts/assert_audit_logging.sh

assert-metrics:
	KUBECONFIG=$(KUBECONFIG) ./tests/scripts/assert_metrics.sh

assert-nginx-ingress: MEMBERS := 6
assert-nginx-ingress:
	NAMESPACE="ingress-nginx" \
	KUBECONFIG=${KUBECONFIG} \
	TO_CHECK="-l app.kubernetes.io/name=ingress-nginx" \
	./tests/scripts/assert_nginx_controller.sh;
	./tests/scripts/assert_members.sh ${MEMBERS} $(CLUSTER_NAME) Ingress-HTTP-$(CLUSTER_NAME)
	./tests/scripts/assert_members.sh ${MEMBERS} $(CLUSTER_NAME) Ingress-HTTPS-$(CLUSTER_NAME)
	# assert green blue ingress works
	KUBECONFIG=${KUBECONFIG} ./tests/scripts/blue_green_ingress.sh

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
	./tests/scripts/assert_members.sh $(NUM) $(CLUSTER_NAME) master-pool-$(CLUSTER_NAME)

show-nodes:
	@echo "Waiting for nodes to join ..."
	for i in `seq 1 5`; do \
		sleep 1; \
		kubectl get nodes -o wide --kubeconfig=${KUBECONFIG} | grep -v "No resources found."; \
	done

test-cinder-volumes:
	KUBECONFIG=${KUBECONFIG} ./tests/scripts/assert-cinder-volumes.sh

clean-cinder-volumes:
	kubectl --kubeconfig=${KUBECONFIG} delete pvc --kubeconfig=${KUBECONFIG} --all;


reset-config:
	git checkout $(CONFIG_FILE)


check-cluster-dns:
	./tests/scripts/test-cluster-dns.sh $(KUBECONFIG)

clean-lb-after-integration-test:
	@kubectl describe service external-http-nginx-service --kubeconfig=${KUBECONFIG};
	@kubectl delete service external-http-nginx-service --kubeconfig=${KUBECONFIG}
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

# FIP is selected from 1 of 2 floating IPs which are allocated to the project.
# The jq magic line simply selects one of those in the correct network (since we
# can select a floating IP from an internal network or from the public network).
update-config: TESTID ?= 0
update-config: KEY ?= kube  ## create a test configuration file
update-config: IMAGE ?= $(shell openstack image list -c Name -f value --sort name:desc | grep 'koris-ubuntu-${UBUNTU_VER}-[[:digit:]]' | head -n 1)
update-config:	FIP ?= $(shell openstack floating ip list -f json | jq -r -c  '.[$(TESTID)]  | select(.Port == null and ."Floating Network"=="c019250b-aea8-497e-9b3b-fd94020684b6")."Floating IP Address"')
update-config:
	@sed -i "s/%%CLUSTER_NAME%%/$(CLUSTER_NAME)/g" $(CONFIG_FILE)
	@sed -i "s/%%LATEST_IMAGE%%/$(IMAGE)/g" $(CONFIG_FILE)
	@sed -i "s/keypair: 'kube'/keypair: ${KEY}/g" $(CONFIG_FILE)
	@sed -i 's/\s*floatingip: "%%FLOATING_IP%%"/  floatingip: '$(FIP)'/g' $(CONFIG_FILE)
	@cat $(CONFIG_FILE)

clean-cluster: update-config
	$(PY) -m coverage run -m koris -v debug destroy $(CONFIG_FILE) --force

clean-floating-ips:
	for ip in $$(openstack floating ip list -f json | jq -c -r '.[-2:] | .[].ID'); do \
		openstack floating ip delete $$ip; \
	done

clean-all:
	@if [ -r tests/koris_test.updated.yml ]; then \
		mv -v tests/koris_test.updated.yml  $(CONFIG_FILE); \
		if [ -r tests/koris_test.master.yml ]; then \
			sed -i 's/n-masters:\ 3/n-masters:\ 4/' $(CONFIG_FILE); \
		fi; \
	else \
		$(MAKE) reset-config update-config; \
	fi
	$(PY) -m coverage run -m koris -v debug destroy $(CONFIG_FILE) --force
	@git checkout $(CONFIG_FILE)
	@rm -fv ${KUBECONFIG}
	@rm -vfR certs-${CLUSTER_NAME}

clean-network-ports:  ## remove dangling ports in Openstack
	openstack port delete $$(openstack port list -f value -c id -c status | grep DOWN | cut -f 1 -d" " | xargs)

check-sonobuoy: SONOBUOY_VERSION ?= 0.16.4
check-sonobuoy: SONOBUOY_URL = https://github.com/vmware-tanzu/sonobuoy/releases/download/v$(SONOBUOY_VERSION)/sonobuoy_$(SONOBUOY_VERSION)_linux_amd64.tar.gz
check-sonobuoy: SONOBUOY_COMPLETED_INDICATOR = "Sonobuoy has completed"
check-sonobuoy:SONOBUOY_CHECK_TIMEOUT_SECONDS = 14400
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
	docker run --rm -w /usr/src -v $(PWD):/usr/src/ $(ORG)/koris-builder:$(TAG) bash -c "make install build-exec PY=python3.6"

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

destroy-cluster-with-floating-ip: FILENAME ?= $(subst .yml,-floating-ip.yml, $(CONFIG_FILE))
destroy-cluster-with-floating-ip: reset-config update-config-with-floating-ip
	$(PY) -m coverage run -m koris -v debug destroy -f $(FILENAME)
launch-gitlab-worker: USERDATA ?= tests/misc/provision-gitlab-worker.sh
launch-gitlab-worker: NETWORK ?= koris-net
launch-gitlab-worker:  # start a gitlab worker
	@[ "${IMAGE}" ] || ( echo ">> IMAGE is not set"; exit 1 )
	@[ "${AZ}" ] || ( echo ">> AZ is not set"; exit 1 )
	@[ "${KEY}" ] || ( echo ">> KEY is not set"; exit 1 )
	@[ "${TOKEN}" ] || ( echo ">> TOKEN is not set"; exit 1 )
	@[ "${WORKER}" ] || ( echo ">> WORKER is not set"; exit 1 )
	sed -i '3iexport RUNNER_TOKEN="$(TOKEN)"' $(USERDATA)
	sed -i '4iexport WORKER="$(WORKER)"' $(USERDATA)
	openstack volume create --size 25 --bootable --availability-zone $(AZ) --type BSS-Performance-Storage --image $(IMAGE) gitlab-${WORKER}-volume
	sleep 30;
	openstack server create --network $(NETWORK) --flavor ECS.C1.4-8 --availability-zone $(AZ) --key-name $(KEY) \
		--security-group default --volume gitlab-$(WORKER)-volume gitlab-runner-$(WORKER) \
		--user-data $(USERDATA);

# vim: tabstop=4 shiftwidth=4
#
