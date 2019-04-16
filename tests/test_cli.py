import os
import subprocess

import pytest

# from .testdata import NAUGHTY_STRINGS
from koris.koris import delete_node


def _get_clean_env():
    """
    A helper method that ensures that it seems that we do not have an RC
    file sourced.
    """
    env = {}
    for (key, val) in dict(os.environ).items():
        if not key.startswith("OS_"):
            env[key] = val
    return env


def test_help():
    """
    It should be possible to call koris --help without sourcing an
    RC file.
    """
    cmd = ['koris', '--help']
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=_get_clean_env())
    stdout, stderr = proc.communicate()
    output = stdout.decode("utf-8").strip()
    assert proc.returncode == 0
    assert "usage: koris" in output


def test_need_rc_file():
    """
    For building a cluster, we need to source the RC file.
    """
    cmd = ['koris', 'apply', 'tests/koris_test.yml']
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=_get_clean_env())
        proc.communicate()

        # We should not reach that, since an AssertionError should be thrown.
        assert False
    except AssertionError:
        pass


def test_delete_node():
    invalid_names = ["", None]

    for name in invalid_names:
        with pytest.raises(ValueError):
            delete_node(name)


# def test_koris_delete():
#     conf = 'tests/koris_test.yml'
#     resource_valid = ["cluster", "node"]
#     resource_invalid = ["asd"]
#     resource_invalid.extend(NAUGHTY_STRINGS)

#     for res in resource_valid:
#         cmd = ["koris", "delete", res, "--name", "test", conf]
#         subprocess.run(cmd, check=True)

#     for res in resource_invalid:
#         cmd = ["koris", "delete", res, conf]
#         with pytest.raises(subprocess.CalledProcessError):
#             subprocess.run(cmd, check=True)


# def test_koris_delete_node():
#     """Empty --name should exit with non-zero"""
#     cmd = ["koris", "delete", "node", "--name", "", 'tests/koris_test.yml']
#     with pytest.raises(subprocess.CalledProcessError):
#         subprocess.run(cmd, check=True)
