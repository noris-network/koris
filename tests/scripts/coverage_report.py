#!/bin/python3
"""
A script to generate a comprehensive coverage report based on a set of
.coverage files from the previous steps.

Usage: script.py <artifact1> <artifact2> <artifact3> ...
"""

# import gitlab
# import os
import sys

# from urllib.parse import urlparse


CI_PROJECT_URL = "https://gitlab.noris.net/PI/koris/"


def main(argv):
    pass
    """URL = urlparse(os.getenv("CI_PROJECT_URL", CI_PROJECT_URL))
    gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                       private_token=os.getenv("ACCESS_TOKEN"))

    # TODO: find out how to get artifacts

    running_pipelines = [lin for lin in project.pipelines.list() if
                         lin.attributes['status'] == 'running']

    running_pipelines = sorted(running_pipelines, key=lambda x: x.id)
    # print(running_pipelines)
    # myID = int(os.getenv("CI_PIPELINE_ID"))


    project = gl.projects.get(os.getenv("CI_PROJECT_ID", 1260))
    branch = project.branches.get(sys.argv[1])

    if branch.attributes['protected']:
        branch.unprotect()
        print("Successfully removed protection of %s" % sys.argv[1])
    else:
        branch.protect()
        print("Successfully restored protection of %s" % sys.argv[1])
"""


if __name__ == "__main__":
    main(sys.argv)
