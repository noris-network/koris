MAINTAINERS
===========

This documents explains how to a release:

1. You need a GPG key! If you don't have one, create one.
2. You need an access token for gitlab, create one and keep it safe.

To do a release X.Y.Z do the following steps:

1. `make start-release VER=vX.Y.Z`
2. edit `ChangeLog` and rename it to TAGMESSAGE`
3. `make complete-release VER=vX.Y.Z ACCESS_TOKEN=<your-secret-key>`

If you encountered merge conflicts, you need to fix them first and 
then proceed manually:

> Below assumes you are on `master` after merging the branch
> `prepare_${VER}`.

1. Create a tag: `git tag -f -s ${VER} -F TAGMESSAGE`
2. Un-protect the `master` branch: `python3 tests/scripts/protect-un-protect.py master`
  Make sure the output says `Successfully removed protection of master`
3. Push to `master`: `git push origin master --tags`
4. Re-protect the `master` branch: `python3 tests/scripts/protect-un-protect.py master`
5. Finish the release: `make -f release.mk finish-release VER=vX.Y.Z` 

If for some reason you encounter an error in any of the stages, you can
do:

`make abort-release VER=vX.Y.Z`

