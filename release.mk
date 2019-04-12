check-env:
ifndef VER
	$(error VER is undefined)
endif

check-api-key:
ifndef ACCESS_TOKEN
	$(error ACCESS_TOKEN is undefined)
endif

start-release: check-env
	@echo "checking out branch prepare_"$(VER)
	@git checkout -b prepare_$(VER)
	@sudo rm -Rf koris.egg-info dist/
	@echo "create a git tag"
	git tag -s $(VER) -m "tmp-tag"
	@python setup.py sdist
	@echo "Edit ChangeLog manually and rename it to TAGMESSAGE"

do-bump: NVER = $(subst v,,$(VER))
do-bump: check-env
	echo $(NVER)
	sed -i "s/[[:digit:]]\+\.[[:digit:]]\+\.[[:digit:]]\+/$(NVER)/g" koris/__init__.py

do-release: do-bump check-api-key
	git add koris/__init__.py
	git commit -m "Bump version to $(VER)"
	git checkout master
	git merge prepare_$(VER) --ff
	git tag -f -s $(VER) -F TAGMESSAGE
	python3 tests/scripts/protect-un-protect.py

finish-release: check-env check-api-key
	git checkout dev
	git branch -D prepare_$(VER)
	git merge --ff master
	git rebase
	rm -f TAGMESSAGE
	python3 tests/scripts/protect-un-protect.py

# vim: tabstop=4 shiftwidth=4
