SHELL := /bin/bash
.PHONY: clean clean-test clean-pyc clean-build docs help integration-patch-wait \
	clean-lb-after-integration-test \
	clean-lb

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
CLUSTER_NAME = $(REV_NUMBER)$(BUILD_SUFFIX)
KUBECONFIG ?= koris-pipe-line-$(CLUSTER_NAME)-admin.conf

BROWSER := $(PY) -c "$$BROWSER_PYSCRIPT"


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
	rm -fr htmlcov/
	rm -fr .pytest_cache

lint: pylint flake8  ## check style with pylint and flake8

pylint: ## check style with pylint
	pylint --rcfile=.pylintrc kolt || pylint-exit $$?

flake8: ## check style with flake8
	flake8 kolt tests

test: ## run tests quickly with the default Python
	py.test

coverage: ## check code coverage quickly with the default Python
	$(PY) -m pytest -vv --cov .
	#coverage report -m
	#coverage html
	#$(BROWSER) htmlcov/index.html

docs: ## generate Sphinx HTML documentation, including API docs
	sphinx-apidoc -o docs/ kolt
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


servedocs: docs ## compile the docs watching for changes
	watchmedo shell-command -p '*.rst' -c '$(MAKE) -C docs html' -R -D .

release: dist ## package and upload a release
	twine upload dist/*

dist: clean ## builds source and wheel package
	$(PY) setup.py sdist
	$(PY) setup.py bdist_wheel
	ls -l dist

install: clean ## install the package to the active Python's site-packages
	$(PY) setup.py install

integration-test: ## run the complete integration test from you local machine
integration-test: \
	reset-config \
	launch-cluster \
	integration-run \
	integration-wait \
	integration-patch-wait \
	integration-patch \
	integration-expose \
	expose-wait \
	curl-run \
	clean-lb-after-integration-test


launch-cluster: KEY ?= kube  ## launch a cluster with KEY=your_ssh_keypair
launch-cluster: update-config
	kolt k8s tests/koris_test.yml


show-nodes:
	kubectl get nodes -o wide --kubeconfig=${KUBECONFIG}

integration-run:
	kubectl run nginx --image=nginx --port=80 --kubeconfig=${KUBECONFIG}
	# wait for the pod to be available
	@echo "started"


integration-wait:
	until kubectl describe pod nginx --kubeconfig=${KUBECONFIG} > /dev/null; \
		do \
	        echo "Waiting for container...." ;\
		sleep 2; \
		done

	echo "The pod is scheduled"


integration-patch-wait:
	STATUS=`kubectl get pod --selector=run=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`;\
	while true; do \
		if [ "Running" == "$${STATUS}" ]; then \
			break; \
		fi; \
		echo "pod is not running"; \
		STATUS=`kubectl get pod --selector=run=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`;\
		echo ${STATUS}; \
		sleep 1; \
	done ; \


integration-patch:
	kubectl patch deployment.apps nginx -p \
		'{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer":"true"}}}}}' \
		--kubeconfig=${KUBECONFIG}

integration-expose:
	kubectl expose deployment nginx --type=LoadBalancer --name=nginx --kubeconfig=${KUBECONFIG}


expose-wait:
	while true; do \
		IP=`kubectl get service --selector=run=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}'`; \
		if [ ! -z $${IP} ]; then \
			echo "breaking "; \
			break; \
		fi; \
		sleep 1; \
		echo "Waiting for loadBalancer to get an IP\n";\
	done; \
	echo "Got an IP!"; \
	echo "Echo $${IP}"


reset-config:
	git checkout tests/koris_test.yml


curl-run:
	IP=`kubectl get service --selector=run=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}'`; \
	echo $${IP}; \
	while true; do \
		curl http://$${IP}:80;\
		if [ $$? -eq 0 ]; then \
			break; \
		fi; \
		sleep 2; \
	done

clean-lb-after-integration-test:
	kubectl delete service nginx --kubeconfig=${KUBECONFIG}
	# fuck yeah, wait for the service to die before deleting the cluster
	while true; do \
		kubectl get service --selector=run=nginx --kubeconfig=${KUBECONFIG}; \
		if [ $$? -eq 0 ]; then \
			break; \
		fi; \
	done;
	sleep 90


clean-lb: ## delete a loadbalancer with all it's components
	$(call ndef,LOADBALANCER_NAME)
	LOADBALANCER_NAME=$(LOADBALANCER_NAME) $(PY) tests/scripts/load_balacer_create_and_destroy.py destroy

security-checks:
	echo "Running security checks for K8S master nodes..."
	echo "TODO: If we have a self-containing cluster, then we can acitvate the following comment in the source code."
	# kubectl run --rm -i -t kube-bench-master --image=aquasec/kube-bench:latest --restart=Never \
	#	--overrides="{ \"apiVersion\": \"v1\", \"spec\": { \"hostPID\": true, \"nodeSelector\": { \"kubernetes.io/role\": \"master\" }, \"tolerations\": [ { \"key\": \"node-role.kubernetes.io/master\", \"operator\": \"Exists\", \"effect\": \"NoSchedule\" } ] } }" -- master --version 1.11
	echo "Running security checks for K8S worker nodes..."
	kubectl run --kubeconfig=${KUBECONFIG} --rm -i -t kube-bench-node --image=aquasec/kube-bench:latest --restart=Never \
		--overrides="{ \"apiVersion\": \"v1\", \"spec\": { \"hostPID\": true } }" -- node --version 1.11

update-config: KEY ?= kube  ## create a test configuration file
update-config:
	sed -i "s/%%CLUSTER_NAME%%/koris-pipe-line-$(CLUSTER_NAME)/g" tests/koris_test.yml
	sed -i "s/%%date%%/$$(date '+%Y-%m-%d')/g" tests/koris_test.yml
	sed -i "s/keypair: 'kube'/keypair: ${KEY}/g" tests/koris_test.yml
	cat tests/koris_test.yml


clean-cluster: update-config
	kolt destroy tests/koris_test.yml --force

clean-all:
	kolt destroy tests/koris_test.yml --force
	git checkout tests/koris_test.yml
	rm -fv ${KUBECONFIG}
	rm -vfR certs-koris-pipe-line-${CLUSTER_NAME}

clean-network-ports:  ## remove dangling ports in Openstack
	openstack port delete $$(openstack port list -f value -c id -c status | grep DOWN | cut -f 1 -d" " | xargs)
