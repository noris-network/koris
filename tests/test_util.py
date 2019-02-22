import io
import unittest.mock

from koris.util.util import KorisVersionCheck
from koris.util.net import is_port, is_ip
from koris.util.hue import red

phtml = """
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>Welcome to Koris’s ! &#8212; koris v0.9.2-14-g8a53b27 documentation</title>
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
        xpctd = red("Version 0.9.2 of Koris was released, you should upgrade!") + "\n"
        assert val == xpctd


def test_version_is_the_same():
    with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as p1:
        KorisVersionCheck(phtml).check_is_latest("0.9.2")
        val = p1.getvalue()
        assert val is ""


def test_version_is_newer():
    with unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as p1:
        KorisVersionCheck(phtml).check_is_latest("0.9.3.dev57")
        val = p1.getvalue()
        assert val is ""


def test_web_site_is_not_avail():
    assert KorisVersionCheck("").version == "0.0.0"


def test_is_port():
    valid = [0, 1, 5, 80, 443, 65535]
    invalid = [None, "", 1.4, [], {}, ()]
    for p in valid:
        assert is_port(p)
    for p in invalid:
        assert is_port(p) is False


def test_is_ip():
    valid = [0, 1, 2, 3, "::0", "::", "1.2.3.4",
             "2001:0db8:0000:0000:0000:ff00:0042:8329"]
    invalid = [None, "", 1.23, [], {}, (), "300.400.500.600"]
    for i in valid:
        assert is_ip(i)
    for i in invalid:
        assert is_ip(i) is False
