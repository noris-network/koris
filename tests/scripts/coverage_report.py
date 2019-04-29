#!/usr/bin/env python3

"""
A script to generate a comprehensive coverage report based on a set of
.coverage files from the previous steps.
"""

import os
import subprocess

FILES = [".coverage.unit-test", ".coverage.build-cluster",
         ".coverage.add-master", ".coverage.add-nodes",
         ".coverage.delete-master", ".coverage.delete-nodes",
         ".coverage.destroy"]


def main():
    actual_files = []

    # only combine files that are actually existing, print warning for every
    # file that does not exist
    for file in FILES:
        if os.path.isfile(file):
            actual_files.append(file)
        else:
            print("Could not find coverage info file: {}".format(file))

    # call python combine
    cmd = ["python3", "-m", "coverage", "combine"]
    cmd.extend(actual_files)
    print(cmd)
    subprocess.run(cmd, check=True)

    print("Successfully combined the coverage reports.")


if __name__ == "__main__":
    main()
