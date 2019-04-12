MAINTAINERS
===========

This documents explains how to a release:

1. You need a GPG key! If you don't have one, create one.
2. You need an access token for gitlab, create one and keep it safe.

To do a release X.Y.Z do the following steps:

1. `make start-relese VER=vX.Y.Z`
2. edit `ChangeLog` and rename it to TAGMESSAGE`
3. `make do-release VER=vX.Y.Z` ACCESS_TOKEN=<your-secret-key>
4. `make finish release`
