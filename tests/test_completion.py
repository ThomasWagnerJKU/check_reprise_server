"""Tests for the bash completion in completions/check_reprise_server."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "check_reprise_server")
COMPLETION = os.path.join(ROOT, "completions", "check_reprise_server")


def complete(*words, command="check_reprise_server", cwd=None, env=None):
    """The candidates bash offers for the last of words, which may be empty."""
    words = (command,) + words
    script = 'source "$1"; shift; COMP_WORDS=("$@"); COMP_CWORD=$(($# - 1)); ' \
             '$(complete -p "$1" | sed -E "s/.*-F ([^ ]+) .*/\\1/"); printf "%s\\n" "${COMPREPLY[@]}"'
    result = subprocess.run(["bash", "-c", script, "bash", COMPLETION] + list(words),
                            capture_output=True, text=True, check=True, cwd=cwd, env=env)
    return [line for line in result.stdout.split("\n") if line]


def help_options():
    """The option strings --help lists."""
    text = subprocess.run([PLUGIN, "--help"], capture_output=True, text=True, check=True).stdout
    options = set()
    for line in text.split("\n"):
        match = re.match(r"\s{2}(-\S.*?)(?:\s{2}|$)", line)
        if match:
            options.update(re.findall(r"(?<![\w-])-{1,2}[A-Za-z][\w-]*", match.group(1)))
    return options


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class CompletionTests(unittest.TestCase):
    def test_syntax(self):
        subprocess.run(["bash", "-n", COMPLETION], check=True)

    def test_offers_exactly_the_options_of_help(self):
        self.assertEqual(set(complete("")), help_options())

    def test_option_prefix(self):
        self.assertEqual(complete("--r"), ["--rlmutil"])

    def test_files(self):
        with tempfile.TemporaryDirectory() as directory:
            open(os.path.join(directory, "rlmutil"), "w").close()
            self.assertEqual(complete("-l", "rlm", cwd=directory), ["rlmutil"])
            self.assertEqual(complete("--rlmutil", "=", "rlm", cwd=directory), ["rlmutil"])

    def test_hosts(self):
        with tempfile.NamedTemporaryFile("w", suffix=".hosts") as hosts:
            hosts.write("192.0.2.1 licsrv\n")
            hosts.flush()
            env = dict(os.environ, HOSTFILE=hosts.name)
            self.assertEqual(complete("-H", "lics", env=env), ["licsrv"])
            self.assertEqual(complete("--ssh", "=", "lics", env=env), ["licsrv"])
            self.assertEqual(complete("-s", "root@lics", env=env), ["root@licsrv"])

    def test_no_candidates_for_values(self):
        for option in ("-w", "--critical", "-p", "--timeout"):
            self.assertEqual(complete(option, ""), [], option)


if __name__ == "__main__":
    unittest.main()
