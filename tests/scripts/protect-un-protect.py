#!/bin/python3
import os
import sys

from urllib.parse import urlparse

import gitlab


URL = urlparse(os.getenv("CI_PROJECT_URL", "https://gitlab.noris.net/PI/koris/"))
gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                   private_token=os.getenv("ACCESS_TOKEN"))

project = gl.projects.get(os.getenv("CI_PROJECT_ID", 1260))

branch = project.branches.get(sys.argv[1])

if branch.attributes['protected']:
    branch.unprotect()
else:
    branch.protect()
