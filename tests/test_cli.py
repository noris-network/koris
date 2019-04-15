import os
import subprocess


def test_help():
    """
    It should be possible to call koris --help without sourcing an
    RC file.
    """
    cmd = ['koris', '--help']
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    output = stdout.decode("utf-8").strip()
    assert proc.returncode == 0
    assert "usage: koris" in output


def test_need_rc_file():
    """
    For building a cluster, we need to source the RC file.
    """
    cmd = ['koris', 'apply', 'tests/koris_test.yml']

    # ensure that it seems that we do not have an RC file sourced.
    env = {}
    for (key, val) in dict(os.environ).items():
        if not key.startswith("OS_"):
            env[key] = val

    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env={})
        proc.communicate()

        # We should not reach that, since an AssertionError should be thrown.
        assert False
    except AssertionError:
        pass
