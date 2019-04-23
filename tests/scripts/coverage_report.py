#!/bin/python3
"""
A script to generate a comprehensive coverage report based on a set of
.coverage files from the previous steps.
"""

import gitlab
import os
import subprocess
import sys

from urllib.parse import urlparse


CI_PROJECT_URL = "https://gitlab.noris.net/PI/koris/"
CI_PROJECT_ID = "1260"

# name of the job and artifact files to use from this job
FILES = {
    "unittest": [".coverage.unit-test"],
    "build-cluster": [".coverage.build-cluster"],
    "add-master": [".coverage.add-master"],
    "add-nodes": [".coverage.add-nodes"],
    "delete-added-master": [".coverage.delete-master"],
    "delete-added-node": [".coverage.delete-nodes"],
    "cleanup": [".coverage.destroy"],
}


def main(argv):
    URL = urlparse(os.getenv("CI_PROJECT_URL", CI_PROJECT_URL))
    gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                       private_token=os.getenv("ACCESS_TOKEN"))
    project = gl.projects.get(os.getenv("CI_PROJECT_ID", CI_PROJECT_ID))

    pipeline = project.pipelines.get(os.getenv("CI_PIPELINE_ID"))
    jobs = pipeline.jobs.list(all=True)

    for job in jobs:
        # check if we have a job we want to extract data from
        if job.name in FILES:
            print(job.name)  # TODO: remove if we know it works

            # find artifact archive that cotnaints the interesting files
            zipfn = "___artifacts.zip"
            with open(zipfn, "wb") as f:
                job.artifacts(streamed=True, action=f.write)
                subprocess.run(["unzip", "-bo", zipfn])

                subprocess.run(["ls", "-la"])  # TODO: remove if it works

                os.unlink(zipfn)


if __name__ == "__main__":
    main(sys.argv)
