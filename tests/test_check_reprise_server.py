"""Tests for check_reprise_server, with a fake rlmutil replaying recorded rlmstat output."""
import datetime
import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(os.path.dirname(HERE), "check_reprise_server")
FIXTURES = os.path.join(HERE, "fixtures")

loader = importlib.machinery.SourceFileLoader("check_reprise_server", PLUGIN)
spec = importlib.util.spec_from_loader("check_reprise_server", loader)
check_reprise_server = importlib.util.module_from_spec(spec)
loader.exec_module(check_reprise_server)

TODAY = datetime.date(2099, 9, 1)

# rlmutil rlmstat -a -c PORT@HOST: prints $FAKE_A and logs its arguments
FAKE_RLMUTIL = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
cat "$FAKE_A"
"""

# ssh [-o OPTION]... HOST COMMAND: runs COMMAND locally
FAKE_SSH = """#!/bin/sh
echo "ssh $*" >> "$FAKE_LOG"
[ -n "$FAKE_SSH_DOWN" ] && { echo "ssh: connect to host licsrv port 22: Connection refused" >&2; exit 255; }
for last; do :; done
sh -c "$last"
"""


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as handle:
        return handle.read()


def args(**kwargs):
    values = dict(license="5852@licsrv", warning=check_reprise_server.Range.parse("30:"),
                  critical=check_reprise_server.Range.parse("7:"))
    values.update(kwargs)
    return type("Args", (), values)


class TestCheck(unittest.TestCase):
    """check() on recorded rlmstat output."""

    def check(self, a, today=TODAY, **kwargs):
        state, message, perf = check_reprise_server.check(args(**kwargs), fixture(a), today)
        self.assertNotIn("\n", message)
        return state, message, perf

    def test_ok(self):
        state, message, perf = self.check("up_a.txt")
        self.assertEqual(check_reprise_server.OK, state, message)
        self.assertEqual("3 feature(s), 3 of 2005 licenses in use, embeowulf expires on 2099-10-01, in 30 days",
                         message)

    def test_usage_of_all_features(self):
        state, message, perf = self.check("up_a.txt")
        self.assertEqual(["days_left=30;30;7", "'xgeom'=3;;;0;1000", "'embeowulf'=0;;;0;5",
                          "'soncustomer'=0;;;0;1000"], perf)

    def test_earliest_expiry_warning(self):
        state, message, perf = self.check("up_a.txt", today=datetime.date(2099, 9, 10))
        self.assertEqual(check_reprise_server.WARNING, state, message)
        self.assertTrue(message.startswith("embeowulf expires on 2099-10-01, in 21 days"), message)

    def test_earliest_expiry_critical(self):
        state, message, perf = self.check("up_a.txt", today=datetime.date(2099, 9, 28))
        self.assertEqual(check_reprise_server.CRITICAL, state, message)
        self.assertIn("days_left=3;30;7", perf)

    def test_expired(self):
        state, message, perf = self.check("up_a.txt", today=datetime.date(2099, 10, 3))
        self.assertEqual(check_reprise_server.CRITICAL, state, message)
        self.assertIn("embeowulf expired on 2099-10-01, 2 days ago", message)
        self.assertIn("days_left=-2;30;7", perf)

    def test_permanent(self):
        state, message, perf = self.check("permanent_a.txt")
        self.assertEqual(check_reprise_server.OK, state, message)
        self.assertIn("no feature expires", message)
        self.assertFalse([item for item in perf if item.startswith("days_left")], perf)

    def test_server_down(self):
        with self.assertRaises(check_reprise_server.PluginError) as caught:
            self.check("down_a.txt")
        self.assertEqual(check_reprise_server.CRITICAL, caught.exception.state)
        self.assertEqual('license server 5852@licsrv is down: Cannot connect to server (comm: -4)Connection '
                         'refused (errno: 111)', caught.exception.message)

    def test_isv_server_down(self):
        with self.assertRaises(check_reprise_server.PluginError) as caught:
            self.check("isv_down_a.txt")
        self.assertEqual(check_reprise_server.CRITICAL, caught.exception.state)
        self.assertEqual("ISV server sonnetusa is down; license server 5852@licsrv reports no features",
                         caught.exception.message)

    def test_two_isv_shared_feature_name(self):
        state, message, perf = self.check("two_isv_a.txt")
        self.assertEqual(["'sonnetusa/shared'=1;;;0;4", "'otherisv/shared'=2;;;0;8", "'layout'=0;;;0;2"], perf)

    def test_no_features(self):
        text = fixture("up_a.txt").split("license pool status")[0]
        with self.assertRaises(check_reprise_server.PluginError) as caught:
            check_reprise_server.check(args(), text, TODAY)
        self.assertEqual(check_reprise_server.UNKNOWN, caught.exception.state)

    def test_parse_expiry(self):
        self.assertEqual(datetime.date(2027, 9, 29), check_reprise_server.parse_expiry("29-sep-2027"))
        self.assertEqual(datetime.date(2026, 1, 5), check_reprise_server.parse_expiry("5-JAN-2026"))
        self.assertIsNone(check_reprise_server.parse_expiry("permanent"))
        with self.assertRaises(ValueError):
            check_reprise_server.parse_expiry("soon")


class TestCommandLine(unittest.TestCase):
    """The plugin as Nagios runs it."""

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.rlmutil = self.executable("rlmutil", FAKE_RLMUTIL)
        self.executable("ssh", FAKE_SSH)
        self.log = os.path.join(self.tempdir, "log")
        open(self.log, "w").close()

    def tearDown(self):
        for name in os.listdir(self.tempdir):
            os.remove(os.path.join(self.tempdir, name))
        os.rmdir(self.tempdir)

    def executable(self, name, content):
        path = os.path.join(self.tempdir, name)
        with open(path, "w") as handle:
            handle.write(content)
        os.chmod(path, stat.S_IRWXU)
        return path

    def run_plugin(self, *argv, a="up_a.txt", **env):
        environ = dict(os.environ, FAKE_A=os.path.join(FIXTURES, a),
                       FAKE_LOG=self.log, PATH=self.tempdir + os.pathsep + os.environ["PATH"], **env)
        result = subprocess.run([sys.executable, PLUGIN] + list(argv), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True, env=environ)
        return result

    def logged(self):
        with open(self.log) as handle:
            return handle.read().splitlines()

    def test_ok(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "licsrv", "-p", "5852")
        self.assertEqual(check_reprise_server.OK, result.returncode, result)
        self.assertRegex(result.stdout, r"^RLM OK - 3 feature\(s\), 3 of 2005 licenses in use, embeowulf expires "
                                        r"on 2099-10-01, in \d+ days \| days_left=\d+;30;7 'xgeom'=3;;;0;1000 ")
        self.assertEqual(1, len(result.stdout.splitlines()))
        self.assertEqual(["rlmstat -a -c 5852@licsrv"], self.logged())

    def test_default_port(self):
        self.run_plugin("-l", self.rlmutil, "-H", "licsrv")
        self.assertEqual("rlmstat -a -c 5053@licsrv", self.logged()[0])

    def test_thresholds(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "licsrv", "-w", "40000:", "-c", "1:")
        self.assertEqual(check_reprise_server.WARNING, result.returncode, result)
        self.assertIn("days_left=", result.stdout)
        self.assertIn(";40000;1 ", result.stdout)

    def test_server_down(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "licsrv", "-p", "5852", a="down_a.txt")
        self.assertEqual(check_reprise_server.CRITICAL, result.returncode, result)
        self.assertTrue(result.stdout.startswith("RLM CRITICAL - license server 5852@licsrv is down: "),
                        result.stdout)

    def test_timeout(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "licsrv", "-p", "5852", "-t", "1", FAKE_SLEEP="5")
        self.assertEqual(check_reprise_server.CRITICAL, result.returncode, result)
        self.assertEqual("RLM CRITICAL - no answer from 5852@licsrv within 1s\n", result.stdout)

    def test_rlmutil_missing(self):
        result = self.run_plugin("-l", os.path.join(self.tempdir, "nothing"), "-H", "licsrv")
        self.assertEqual(check_reprise_server.UNKNOWN, result.returncode, result)
        self.assertIn("is not an executable file", result.stdout)

    def test_ssh(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "localhost", "-s", "monitor@licsrv", "-t", "7")
        self.assertEqual(check_reprise_server.OK, result.returncode, result)
        log = self.logged()
        self.assertEqual(1, len([line for line in log if line.startswith("ssh ")]), log)
        self.assertTrue(log[0].startswith("ssh -o BatchMode=yes -o ConnectTimeout=7 monitor@licsrv "), log)
        self.assertEqual("rlmstat -a -c 5053@localhost", log[1])

    def test_ssh_fails(self):
        result = self.run_plugin("-l", self.rlmutil, "-H", "localhost", "-s", "licsrv", FAKE_SSH_DOWN="1")
        self.assertEqual(check_reprise_server.UNKNOWN, result.returncode, result)
        self.assertEqual("RLM UNKNOWN - cannot run rlmutil on licsrv: ssh: connect to host licsrv port 22: "
                         "Connection refused\n", result.stdout)

    def test_usage_error_is_unknown(self):
        result = self.run_plugin("-H", "licsrv")
        self.assertEqual(check_reprise_server.UNKNOWN, result.returncode, result)
        result = self.run_plugin("-l", self.rlmutil, "-H", "licsrv", "-w", "abc")
        self.assertEqual(check_reprise_server.UNKNOWN, result.returncode, result)
        self.assertEqual("RLM UNKNOWN - invalid threshold 'abc'\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
