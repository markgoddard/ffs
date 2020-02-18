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
        self.fuse = subprocess.Popen(["venv/bin/python", "fuse-etcd-v2.py", self.mountpoint])
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

    def _rename_file(self, old, new):
        os.rename(self._get_path(old), self._get_path(new))

    def _truncate_file(self, path, size):
        # os.truncate not available on py2.
        #os.truncate(self._get_path(path), size)
        subprocess.check_call(['truncate', '-s', '{}'.format(size), self._get_path(path)])

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

    def test_rename(self):
        self._write_file("foo", "bar")
        self._rename_file("foo", "baz")
        result = self._read_file("baz")
        self.assertEqual(result, "bar")
        self.assertRaises(IOError, self._read_file, "foo")

    def test_truncate(self):
        self._write_file("foo", "bar")
        self._truncate_file("foo", 2)
        result = self._read_file("foo")
        self.assertEqual(result, "ba")


if __name__ == '__main__':
    unittest.main()
