#!/bin/python3
"""
A script to protect or unprotect a branch - used in our release process

Usage: script.py <branch-name>
"""
import os
import sys

from urllib.parse import urlparse

import gitlab


def main():
    URL = urlparse(os.getenv("CI_PROJECT_URL", "https://gitlab.com/noris-network/koris/"))
    gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                       private_token=os.getenv("ACCESS_TOKEN"))

    project = gl.projects.get(os.getenv("CI_PROJECT_ID", "14251052"))
    branch = project.branches.get(sys.argv[1])

    if branch.attributes['protected']:
        branch.unprotect()
        print("Successfully removed protection of %s" % sys.argv[1])
    else:
        branch.protect()
        print("Successfully restored protection of %s" % sys.argv[1])


if __name__ == "__main__":
    main()
