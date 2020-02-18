#!/usr/bin/env python

import os
import subprocess

import shutil
import unittest


class TestFS(unittest.TestCase):
    mountpoint = "/mnt/etcd"
    test_path = os.path.join(mountpoint, "test")

    def setUp(self):
        super(TestFS, self).setUp()
        self.fuse = subprocess.Popen(["venv/bin/python", "fuse-etcd.py", self.mountpoint])
        mounted = False
        while not mounted:
            output = subprocess.check_output("mount", shell=True)
            for line in output.splitlines():
                if self.mountpoint in line:
                    mounted = True
                    break
        try:
            os.mkdir(self.test_path)
        except OSError as e:
            if e.errno != 17:
                raise

    def tearDown(self):
        try:
            for f in os.listdir(self._get_path("")):
                path = self._get_path(f)
                if os.path.isfile(path):
                    os.unlink(path)
                else:
                    shutil.rmtree(os.path.join(self._get_path(path)))
        finally:
            self.fuse.terminate()
            self.fuse.wait()
        super(TestFS, self).setUp()

    def _get_path(self, path):
        return os.path.join(self.test_path, path)

    def _read_file(self, path):
        with open(self._get_path(path), 'r') as f:
            return f.read()

    def _write_file(self, path, content):
        with open(self._get_path(path), 'w') as f:
            f.write(content)

    def test_open_non_existent(self):
        self.assertRaises(IOError, self._read_file, "invalid")

    def test_write_read(self):
        self._write_file("foo", "bar")
        result = self._read_file("foo")
        self.assertEqual(result, "bar")

    def test_list_dir_empty(self):
        result = os.listdir(self._get_path(""))
        self.assertEqual(result, [])

    def test_list_dir_one_file(self):
        self._write_file("foo", "bar")
        result = os.listdir(self._get_path(""))
        self.assertEqual(result, ["foo"])

    def test_list_dir_two_files(self):
        self._write_file("foo", "bar")
        self._write_file("bar", "baz")
        result = os.listdir(self._get_path(""))
        self.assertEqual(sorted(result), sorted(["foo", "bar"]))


if __name__ == '__main__':
    unittest.main()
