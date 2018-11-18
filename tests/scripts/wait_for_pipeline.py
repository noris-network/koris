#!/bin/python3
import os
import time

from urllib.parse import urlparse
import gitlab


from koris.cloud.openstack import get_clients

_, _, cinder = get_clients()


URL = urlparse(os.getenv("CI_PROJECT_URL", "https://gitlab.noris.net/PI/koris/"))
gl = gitlab.Gitlab(URL.scheme + "://" + URL.hostname,
                   private_token=os.getenv("ACCESS_TOKEN"))


project = gl.projects.get(os.getenv("CI_PROJECT_ID", 1260))


def another_job_running():
    return sum([1 for lin in project.pipelines.list() if lin.attributes['status'] == 'running']) > 1  # noqa


def can_i_run():
    """
    check if other jobs are not in step:
        'build-cluster', 'integration-test', 'security-checks',
        'compliance-checks'
    """
    running_pipelines = [lin for lin in project.pipelines.list() if
                         lin.attributes['status'] == 'running']

    running_pipelines = sorted(running_pipelines, key=lambda x: x.id)
    myID = int(os.getenv("CI_PIPELINE_ID"))

    if myID == running_pipelines[0].id:
        return True
    else:
        return False


def clean_resources():
    """
    Check if there are resources left over.

    Check the Pipeline ID in the resource name, and check if this job is running.
    If the job is failed or cancelled, force deletion of the resource.

    This should work because volumes are named:

        node-2-koris-pipe-line-<COMMITHASH>-<CI_PIPELINE_ID>


    Args:
        running_ids (list): a list of currently running pipeline IDs
    """
    running_ids = [str(lin.id) for lin in project.pipelines.list() if
                   lin.attributes['status'] == 'running']

    volumes = cinder.volumes.list()
    print(volumes)
    volumes = [vol for vol in cinder.volumes.list()
               if not vol.name.endswith(tuple(running_ids))]

    for vol in volumes:
        print(vol, vol.status)
        if vol.status != 'in-use':
            vol.delete()


clean_resources()

while True:
    if can_i_run():
        clean_resources()
    else:
        print("Woha, another job is running ...", flush=True)
        print("I'm waiting ... ", flush=True)
        time.sleep(60)

print("Awesome !!! no jobs and no volume found!")
print("I will run that integration test now!")
