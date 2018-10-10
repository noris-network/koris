.PHONY: clean clean-test clean-pyc clean-build docs help
.DEFAULT_GOAL := help

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

PY ?= python
BROWSER := python -c "$$BROWSER_PYSCRIPT"

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

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

test-all: ## run tests on every Python version with tox
	tox

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
	docker build -t $(ORG)/koris:$(TAG) -f docker/Dockerfile.ubuntu .

docker-push-alpine:
	docker push $(ORG)/koris-alpine:$(TAG)
docker-push:
	docker push $(ORG)/koris:$(TAG)


servedocs: docs ## compile the docs watching for changes
	watchmedo shell-command -p '*.rst' -c '$(MAKE) -C docs html' -R -D .

release: dist ## package and upload a release
	twine upload dist/*

dist: clean ## builds source and wheel package
	python setup.py sdist
	python setup.py bdist_wheel
	ls -l dist

install: clean ## install the package to the active Python's site-packages
	python setup.py install


integration-test: launch-cluster integration-run integration-expose expose-wait curl-run clean-after-integration-test

launch-cluster: KEY ?= kube  ## launch a cluster with KEY=your_ssh_keypair
launch-cluster:
	sed -i "s/%%CLUSTER_NAME%%/koris-pipe-line-$$(git rev-parse --short HEAD)/g" tests/koris_test.yml
	sed -i "s/%%date%%/$$(date '+%Y-%m-%d')/g" tests/koris_test.yml
	sed -i "s/keypair: 'kube'/keypair: ${KEY}/g" tests/koris_test.yml
	kolt k8s tests/koris_test.yml


integration-run: KUBECONFIG := koris-pipe-line-$$(git rev-parse --short HEAD)-admin.conf
integration-run:  ## run the complete integration test from you local machine
	kubectl run nginx --image=nginx --port=80 --kubeconfig=${KUBECONFIG}
	$(shell while [ $(kubectl describe pod nginx --kubeconfig=${KUBECONFIG} | \
		grep "Status:" | cut -d ":" -f2 | tr -d " ") != "Running" ]; \
		do echo "Waiting for container...." ;sleep 2; done;)
	kubectl patch deployment.apps nginx -p \
		'{"spec":{"template":{"metadata":{"annotations":{"service.beta.kubernetes.io/openstack-internal-load-balancer":"true"}}}}}' \
		--kubeconfig=${KUBECONFIG}


integration-expose: KUBECONFIG := koris-pipe-line-$$(git rev-parse --short HEAD)-admin.conf
integration-expose:
	kubectl expose deployment nginx --type=LoadBalancer --name=nginx --kubeconfig=${KUBECONFIG}


expose-wait:
	sleep 200


curl-run: KUBECONFIG := koris-pipe-line-$$(git rev-parse --short HEAD)-admin.conf
curl-run:
	curl http://$(shell kubectl describe service nginx --kubeconfig=${KUBECONFIG} | grep "LoadBalancer Ingress" | cut  -d":" -f2 | tr -d " ")


clean-after-integration-test: KUBECONFIG := koris-pipe-line-$$(git rev-parse --short HEAD)-admin.conf
clean-after-integration-test:
	kubectl delete service nginx --kubeconfig=${KUBECONFIG}
	kolt destroy tests/koris_test.yml --force
	git checkout tests/koris_test.yml
	rm ${KUBECONFIG}
