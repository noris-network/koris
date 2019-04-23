#!/bin/python3
"""
A script to generate a comprehensive coverage report based on a set of
.coverage files from the previous steps.
"""

import gitlab
import os
import sys

from urllib.parse import urlparse


CI_PROJECT_URL = "https://gitlab.noris.net/PI/koris/"
CI_PROJECT_ID = "1260"


def main(argv):
    URL = urlparse(os.getenv("CI_PROJECT_URL", CI_PROJECT_URL))
    gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                       private_token=os.getenv("ACCESS_TOKEN"))
    project = gl.projects.get(os.getenv("CI_PROJECT_ID", CI_PROJECT_ID))

    pipeline = project.pipelines.get(os.getenv("CI_PIPELINE_ID"))
    jobs = pipeline.jobs.list(all=True)

    for job in jobs:
        print(job)


if __name__ == "__main__":
    main(sys.argv)
