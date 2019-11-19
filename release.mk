PY ?= python3

check-env:
ifndef VER
	$(error VER is undefined)
endif

check-api-key:
ifndef ACCESS_TOKEN
	$(error ACCESS_TOKEN is undefined)
endif


define ABORT_PIPELINE
import os
import sys
from urllib.parse import urlparse

import gitlab

URL = urlparse(os.getenv("CI_PROJECT_URL", "https://gitlab.com/noris-network/koris"))
PROJECT_ID=os.getenv("CI_PROJECT_ID", 14251052)
VERSION=os.environ['VER']
REVISION = sys.argv[-1]

gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
	               private_token=os.getenv("ACCESS_TOKEN"))

project = gl.projects.get(PROJECT_ID)

for pl in project.pipelines.list():
    if pl.attributes['sha'] == REVISION and pl.attributes['ref'] != VERSION:
        pl.cancel()
        print("Caneclled pipeline %s" % pl.id)

endef
export ABORT_PIPELINE

start-release: check-env
	@echo "checking out branch prepare_"$(VER)
	@git checkout -b prepare_$(VER)
	sudo rm -Rf koris.egg-info dist/
	git tag -s $(VER) -m "tmp-tag"
	@echo "create a git tag"
	@python setup.py sdist
	@echo "Edit ChangeLog manually and rename it to TAGMESSAGE"

do-bump: NVER = $(subst v,,$(VER))
do-bump: check-env
	echo $(NVER)
	sed -i "s/__version__.=[[:space:]]'[[:digit:]]\+\.[[:digit:]]\+\.[[:digit:]]'\+/__version__ = '$(NVER)'/g" koris/__init__.py

abort-release: check-env
	git checkout dev
	git branch -D prepare_$(VER) || echo "branch not found"
	git tag -d $(VER) || echo "tag not found"
	git push --delete origin $(VER)

do-release: do-bump check-api-key
	git add koris/__init__.py
	git commit -m "Bump version to $(VER)"
	git checkout master
	git merge prepare_$(VER) --ff
	git tag -f -s $(VER) -F TAGMESSAGE
	python3 tests/scripts/protect-un-protect.py master
	git push origin master --tags
	python3 tests/scripts/protect-un-protect.py master

abort-pipeline: check-api-key check-env
	@$(PY) -c "$$ABORT_PIPELINE" "$$(git rev-parse HEAD)"

complete-release: do-release finish-release
	echo "finished release"

finish-release: check-env check-api-key
	git checkout dev
	git branch -D prepare_$(VER)
	git merge --ff master
	rm -f TAGMESSAGE
	git pull
	python3 tests/scripts/protect-un-protect.py dev
	git push origin dev
	python3 tests/scripts/protect-un-protect.py dev

# vim: tabstop=4 shiftwidth=4
