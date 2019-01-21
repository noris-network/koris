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
NETWORK_NAME ?= korispipeline-office-net

BROWSER := $(PY) -c "$$BROWSER_PYSCRIPT"

SONOBUOY_URL = https://github.com/heptio/sonobuoy/releases/download/v0.12.1/sonobuoy_0.12.1_linux_amd64.tar.gz
SONOBUOY_COMPLETED_INDICATOR = Sonobuoy has completed
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
	rm -fr htmlcov/
	rm -fr .pytest_cache

lint: pylint flake8  ## check style with pylint and flake8

pylint: ## check style with pylint
	pylint --rcfile=.pylintrc koris

flake8: ## check style with flake8
	flake8 koris tests

test: ## run tests quickly with the default Python
	py.test

coverage: ## check code coverage quickly with the default Python
	$(PY) -m pytest -vv --cov .
	#coverage report -m
	#coverage html
	#$(BROWSER) htmlcov/index.html

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
	add-nodes \
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
	koris apply tests/koris_test.yml

add-nodes: FLAVOR ?= ECS.UC1.4-4
add-nodes:
	KUBECONFIG=${KUBECONFIG} koris add --amount 2 de-nbg6-1a $(FLAVOR) tests/koris_test.yml
	# wait for the 2 nodes to join.
	# assert cluster has now 5 nodes
	echo "waiting for nodes to join"; \
	until [ $$(kubectl get nodes --kubeconfig=${KUBECONFIG} | grep node | grep Ready -c ) -eq 5 ]; do \
		echo -n "."; \
		sleep 1; \
	done
	@echo "all nodes successfully joined!"

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
	until kubectl describe pod nginx --kubeconfig=${KUBECONFIG} > /dev/null; \
		do \
	        echo "Waiting for container...." ;\
		sleep 2; \
		done

	echo "The pod is scheduled"


integration-patch-wait:
	STATUS=`kubectl get pod --selector=app=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`;\
	echo "Waiting for pod status == Runnig ";\
	while true; do \
		if [ "Running" == "$${STATUS}" ]; then \
			break; \
		fi; \
		STATUS=`kubectl get pod --selector=app=nginx --kubeconfig=${KUBECONFIG} -o jsonpath='{.items[0].status.phase}'`;\
		sleep 1; \
		echo -n "."; \
	done ; \


integration-patch:
	kubectl patch deployment nginx-deployment -p \
		'{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer":"true"}}}}}' \
		--kubeconfig=${KUBECONFIG}

integration-expose:
	kubectl expose deployment nginx-deployment --type=LoadBalancer --kubeconfig=${KUBECONFIG}


expose-wait:
	echo "Waiting for loadBalancer to get an IP\n";\
	while true; do \
		IP=`kubectl get service nginx-deployment --kubeconfig=${KUBECONFIG} -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`; \
		if [ ! -z $${IP} ]; then \
			break; \
		fi; \
		echo -n "."; \
		sleep 1; \
	done; \
	echo "Got an IP!"; \
	echo "Echo $${IP}"


reset-config:
	git checkout tests/koris_test.yml


curl-run:
	IP=`kubectl get service nginx-deployment --kubeconfig=${KUBECONFIG} -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`; \
	echo $${IP}; \
	while true; do \
		curl http://$${IP}:80;\
		if [ $$? -eq 0 ]; then \
			break; \
		fi; \
		sleep 2; \
	done

check-cluster-dns:
	./tests/scripts/test-cluster-dns.sh $(KUBECONFIG)

clean-lb-after-integration-test:
	kubectl describe service nginx-deployment --kubeconfig=${KUBECONFIG}; \
	kubectl delete service nginx-deployment --kubeconfig=${KUBECONFIG}
	# fuck yeah, wait for the service to die before deleting the cluster
	while true; do \
		kubectl get service nginx-deployment --kubeconfig=${KUBECONFIG}; \
		if [ $$? -ne 0 ]; then \
			break; \
		fi; \
	done;
	sleep 60

# to delete a loadbalancer the environment variable LOADBALANCER_NAME needs to
# be set to the cluster's name. For example, if one want to delete the
# loadbalancer koris-pipe-line-6e754fe-7008-lb one would need to set
# LOADBALANCER_NAME to koris-pipe-line-6e754fe-7008 (without the -lb)
clean-lb: ## delete a loadbalancer with all it's components
	$(call ndef,LOADBALANCER_NAME)
	LOADBALANCER_NAME=$(LOADBALANCER_NAME) $(PY) tests/scripts/load_balacer_create_and_destroy.py destroy

security-checks: security-checks-nodes security-checks-masters

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
	echo "Running security checks for K8S worker nodes..."
	kubectl run --kubeconfig=${KUBECONFIG} kube-bench-node --image=aquasec/kube-bench:latest --restart=Never \
		--overrides="{ \"apiVersion\": \"v1\", \"spec\": { \"hostPID\": true } }" -- node --version ${CIS_VERSION}
	sleep 30
	kubectl logs kube-bench-node --kubeconfig=${KUBECONFIG}

update-config: KEY ?= kube  ## create a test configuration file
update-config:
	sed -i "s/%%CLUSTER_NAME%%/koris-pipe-line-$(CLUSTER_NAME)/g" tests/koris_test.yml
	sed -i "s/%%date%%/$$(date '+%Y-%m-%d')/g" tests/koris_test.yml
	sed -i "s/keypair: 'kube'/keypair: ${KEY}/g" tests/koris_test.yml
	sed -i "s/private_net: .*/private_net: '${NETWORK_NAME}'/g" tests/koris_test.yml
	cat tests/koris_test.yml


clean-cluster: update-config
	koris destroy tests/koris_test.yml --force

clean-all:
	if [ -r tests/koris_test.updated.yml ]; then \
		mv -v tests/koris_test.updated.yml tests/koris_test.yml; \
	else \
		$(MAKE) reset-config update-config; \
	fi
	koris destroy tests/koris_test.yml --force
	git checkout tests/koris_test.yml
	rm -fv ${KUBECONFIG}
	rm -vfR certs-koris-pipe-line-${CLUSTER_NAME}

clean-network-ports:  ## remove dangling ports in Openstack
	openstack port delete $$(openstack port list -f value -c id -c status | grep DOWN | cut -f 1 -d" " | xargs)

check-sonobuoy:
	echo "Downloading sonobuoy to check for compliance with kubernetes certification requirements from ${SONOBUOY_URL}"; \
	curl -s -L -o sonobuoy.tgz ${SONOBUOY_URL}; \
	tar --skip-old-files -x -z -f sonobuoy.tgz; \
	echo "Running sonobuoy on the cluster. This can take a very long time (up to 3 hours and more!)..."; \
	./sonobuoy --kubeconfig ${KUBECONFIG} run; \
	# Careful: All errors result in a clean exit as requested by Oz Tiram for this will only be run on the master branch
	if [ $$? -ne 0 ]; then \
		echo "Failed to run sonobuoy!"; \
		exit 0; \
	fi; \
	STARTTIME=`date +%s`; \
	echo "Starttime: `date`"; \
	echo -n "Waiting for result to come in, checking every 5 minutes "; \
	while true; do \
		sleep 300; \
		echo -n "."; \
		CURRTIME=`date +%s`; \
		CURRELAPSED=$$(( CURRTIME - STARTTIME)); \
		if [ $$CURRELAPSED -ge ${SONOBUOY_CHECK_TIMEOUT_SECONDS} ]; then \
			echo -e "\nMaximum alloted time for sonobuoy of ${SONOBUOY_CHECK_TIMEOUT_SECONDS} seconds to complete elapsed without result :["; \
			exit 0; \
		fi; \
		SONOBUOY_CURR_STATUS=`./sonobuoy --kubeconfig ${KUBECONFIG} status`; \
		if [ $$? -ne 0 ]; then \
			echo "Failed to check sonobuoy status!"; \
			exit 0; \
		fi; \
		echo $$SONOBUOY_CURR_STATUS | grep "${SONOBUOY_COMPLETED_INDICATOR}" > /dev/null; \
		if [ $$? -eq 0 ]; then \
			echo -e "\nResults are in! Retrieving and displaying for e2e tests..."; \
			./sonobuoy --kubeconfig ${KUBECONFIG} retrieve; \
			RESULTFILE=`ls | grep *sonobuoy*.tar.gz`; \
			echo -e "\n#####################################"; \
			echo -e "\ņ###### RESULT: ######################"; \
			echo -e "#####################################\n"; \
			./sonobuoy --kubeconfig ${KUBECONFIG} e2e $$RESULTFILE; \
			echo -e "\n#####################################\n"; \
			exit 0; \
		fi; \
	done;

clean-sonobuoy:
	./sonobuoy --kubeconfig ${KUBECONFIG} delete; \
	rm -f sonobuoy.tgz sonobuoy *sonobuoy*.tar.gz

compliance-checks: \
	check-sonobuoy \
	clean-sonobuoy

install-git-hooks:
	pip install git-pylint-commit-hook
	echo "#!/usr/bin/env bash" > .git/hooks/pre-commit
	echo "git-pylint-commit-hook" >> .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit

# vim: tabstop=4 shiftwidth=4
