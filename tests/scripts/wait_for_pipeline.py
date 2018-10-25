#!/bin/python3
import os
import time

from urllib.parse import urlparse

import gitlab

URL = urlparse(os.getenv("CI_PROJECT_URL"))
gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                   private_token=os.getenv("ACCESS_TOKEN"))


project = gl.projects.get(os.getenv("CI_PROJECT_ID"))


while 'running' in [lin.attributes['status'] for lin in project.pipelines.list()]:
    time.sleep(60)
