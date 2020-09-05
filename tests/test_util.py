import io
import unittest.mock

from kiosk.util.util import (KorisVersionCheck, name_validation,
                             k8s_version_validation)
from kiosk.util.hue import red

phtml = """
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Welcome to KIOSK’s ! &#8212; kiosk v0.9.2-14-g8a53b27 documentation</title>
</head>
<body>
</body>
</html>
"""


def test_version_is_older():
    assert KorisVersionCheck(phtml).version == '0.9.2'

    with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as p:
        KorisVersionCheck(phtml).check_is_latest("0.9.1")
        val = p.getvalue()
        xpctd = red("Version 0.9.2 of Kiosk was released, you should upgrade!") + "\n"
        assert val == xpctd


def test_version_is_the_same():
    with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as p1:
        KorisVersionCheck(phtml).check_is_latest("0.9.2")
        val = p1.getvalue()
        assert val == ""


def test_version_is_newer():
    with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as p1:
        KorisVersionCheck(phtml).check_is_latest("0.9.3.dev57")
        val = p1.getvalue()
        assert val == ""


def test_web_site_is_not_avail():
    assert KorisVersionCheck("").version == "0.0.0"


class Test_name_validation(unittest.TestCase):
    def test_names(self):
        """test name_validation func using different cluster-names"""
        cluster_name = "example"
        name = name_validation(cluster_name)
        assert name == cluster_name

        cluster_name = "11-04-2019-example"
        name = name_validation(cluster_name)
        assert name == cluster_name

        cluster_name = "example-11-04-2019"
        name = name_validation(cluster_name)
        assert name == cluster_name

        # assert this raises system exit
        cluster_name = "bad" * 250
        with self.assertRaises(SystemExit):
            name_validation(cluster_name)

        # assert this raises system exit
        cluster_name = "bad:)chars"
        with self.assertRaises(SystemExit):
            name_validation(cluster_name)


def test_k8s_version_validation():
    VALID_VERSIONS = ["1.12.7", "1.13.5", "1.13.6", "1.15.0"]
    INVALID_VERSIONS = [1, None, 1.13, "1", "1.13", "abc"]

    for vers in VALID_VERSIONS:
        print(f"OK:{vers}")
        assert k8s_version_validation(vers) is True

    for vers in INVALID_VERSIONS:
        print(f"NOK: {vers}")
        assert k8s_version_validation(vers) is False
