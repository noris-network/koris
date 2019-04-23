#!/bin/python3
"""
A script to generate a comprehensive coverage report based on a set of
.coverage files from the previous steps.
"""

# import gitlab
# import os
import subprocess
import sys

# from urllib import parse

CI_PROJECT_URL = "https://gitlab.noris.net/PI/koris/"
CI_PROJECT_ID = "1260"

# name of the job and artifact files to use from this job
FILES = {
    "unittest": [".coverage.unit-test"],
    "build-cluster": [".coverage.build-cluster"],
    "add-master": [".coverage.add-master"],
    "add-nodes": [".coverage.add-nodes"],
    "delete-added-master": [".coverage.delete-master"],
    "delete-added-nodes": [".coverage.delete-nodes"],
    "cleanup": [".coverage.destroy"],
}


def main(argv):
    # talk to the GitLab API and download all necessary artifacts
    # TODO: Probably we can remove the whole script / the bottom, since we can
    # do it in the gitlab-ci file directly.
    # TODO: upload HTML file to documentation
    # TODO: adjust badge
    """URL = parse.urlparse(os.getenv("CI_PROJECT_URL", CI_PROJECT_URL))
    gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                       private_token=os.getenv("ACCESS_TOKEN"))
    project = gl.projects.get(os.getenv("CI_PROJECT_ID", CI_PROJECT_ID))

    pipeline = project.pipelines.get(os.getenv("CI_PIPELINE_ID"))
    pipeline_jobs = pipeline.jobs.list(all=True)

    for pipeline_job in pipeline_jobs:
        # check if we have a job we want to extract data from
        if pipeline_job.name in FILES:
            print("Checking job {}".format(pipeline_job.name))

            # we need to convert to a job object in order to download artifacts
            job = project.jobs.get(pipeline_job.id, lazy=True)

            # download every interesting file
            for artifact in FILES[pipeline_job.name]:
                print("Download file {}".format(artifact))
                with open(artifact, "wb") as file:
                    file.write(job.artifact(artifact))
    """
    # call python combine
    cmd = ["python3", "-m", "coverage", "combine"]
    for job in FILES:
        for file in FILES[job]:
            cmd.append(file)

    print(cmd)
    subprocess.run(cmd, check=True)

    print("Successfully combined the coverage reports.")


if __name__ == "__main__":
    main(sys.argv)
