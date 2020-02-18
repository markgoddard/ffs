#!/usr/bin/env python

import os
import os.path
import sys
import errno
import logging
import stat

import etcd3
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations


logging.basicConfig(filename='fuse-etcd.log', filemode='w', level=logging.DEBUG)


MAGIC_DIRECTORY = "__DIRECTORY__"


class File(object):

    def __init__(self, fd, path, flags):
        self.fd = fd
        self.path = path
        self.flags = flags


class EtcdFS(LoggingMixIn, Operations):
    def __init__(self):
        self.client = etcd3.client()
        self.fds = [None] * 1024
        self.logger = logging.getLogger('etcdfs')

    # Helpers
    # =======

    def _create_file(self, path, flags):
        try:
            free_fd = self.fds.index(None)
        except ValueError:
            # TODO
            raise
        self.fds[free_fd] = File(free_fd, path, flags)
        return self.fds[free_fd]

    def _get_file(self, fd):
        return self.fds[fd]

    def _close_file(self, fd):
        self.fds.pop(fd)

    @staticmethod
    def _is_dir(value):
        return value == MAGIC_DIRECTORY

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        # FIXME
        pass

    def chmod(self, path, mode):
        raise NotImplementedError

    def chown(self, path, uid, gid):
        raise NotImplementedError

    def getattr(self, path, fh=None):
        if path == '/':
            return {
                'st_atime': 0,
                'st_ctime': 0,
                'st_gid': 1000, # mark
                'st_mode': stat.S_IFDIR | 0o777,
                'st_mtime': 0,
                'st_nlink': 1,
                'st_size': 4096,
                'st_uid': 1000, # mark
            }
        try:
            value, kv = self.client.get(path)
        except:
            raise FuseOSError(errno.ENOENT)
        else:
            if value is None and kv is None:
                raise FuseOSError(errno.ENOENT)
            else:
                if self._is_dir(value):
                    mode = stat.S_IFDIR | 0o777
                else:
                    mode = stat.S_IFREG | 0o666
                return {
                    'st_atime': 0,
                    'st_ctime': 0,
                    'st_gid': 1000, # mark
                    'st_mode': mode,
                    'st_mtime': 0,
                    'st_nlink': 1,
                    'st_size': len(value) if self._is_dir(value) else 4096,
                    'st_uid': 1000, # mark
                }

    def readdir(self, path, fh):
        yield '.'
        yield '..'
        for _, kv in self.client.get_prefix(path, keys_only=True):
            if os.path.split(kv.key)[0] == path:
                yield os.path.split(kv.key)[-1]

    def readlink(self, path):
        raise NotImplementedError

    def mknod(self, path, mode, dev):
        raise NotImplementedError

    def rmdir(self, path):
        value, kv = self.client.get(file.path)
        success = False
        while not success:
            if value is None:
                return 0
            if not self._is_dir(value):
                raise FuseOSError(errno.ENOTDIR)
            success, results = self.client.transaction(
                compare=[
                    self.client.transactions.version(path) == kv.version,
                ],
                success=[
                    self.client.transactions.delete(path)
                ],
                failure=[
                    self.client.transactions.get(path)
                ],
            )
            if not success:
                value, kv = results[0]
                if value is None:
                    return 0

    def mkdir(self, path, mode):
        created = self._ensure_file(path, mode, MAGIC_DIRECTORY)
        if not created:
            raise FuseOSError(errno.EEXIST)

    def statfs(self, path):
        raise NotImplementedError

    def unlink(self, path):
        self.client.delete(path)
        return 0

    def symlink(self, name, target):
        raise NotImplementedError

    def rename(self, old, new):
        raise NotImplementedError

    def link(self, target, name):
        raise NotImplementedError

    def utimens(self, path, times=None):
        # TODO: update times
        pass

    # File methods
    # ============

    def _ensure_file(self, path, flags, content=""):
        created, result = self.client.transaction(
            compare=[
                self.client.transactions.create(path) == 0,
            ],
            success=[
                self.client.transactions.put(path, content)
            ],
            failure=[]
        )
        return created

    def open(self, path, flags):
        self._ensure_file(path, flags)
        file = self._create_file(path, flags)
        return file.fd

    def create(self, path, mode, fi=None):
        created = self._ensure_file(path, mode)
        if not created:
            raise FuseOSError(errno.EEXIST)
        file = self._create_file(path, mode)
        return file.fd

    def read(self, path, length, offset, fh):
        file = self._get_file(fh)
        assert path == file.path
        value, kv = self.client.get(file.path)
        if value is None:
            return None
        # FIXME: Read only up to end?
        return value[offset:offset+length]

    def write(self, path, buf, offset, fh):
        # Handle get/update/put
        file = self._get_file(fh)
        assert path == file.path
        value, kv = self.client.get(file.path)
        if value is None:
            return None
        success = False
        while not success:
            new_value = value[:offset] + buf + value[offset + len(buf):]
            success, results = self.client.transaction(
                compare=[
                    self.client.transactions.version(path) == kv.version,
                ],
                success=[
                    self.client.transactions.put(path, new_value)
                ],
                failure=[
                    self.client.transactions.get(path)
                ],
            )
            if not success:
                value, kv = results[0]
                if value is None:
                    return None
        return len(buf)

    def truncate(self, path, length, fh=None):
        value, kv = self.client.get(path)
        if value is None:
            return None
        success = False
        while not success:
            if len(value) >= length:
                new_value = value[:length]
            else:
                new_value = value + "\0" * (length - len(length))
            success, results = self.client.transaction(
                compare=[
                    self.client.transactions.version(path) == kv.version,
                ],
                success=[
                    self.client.transactions.put(path, new_value)
                ],
                failure=[
                    self.client.transactions.get(path)
                ],
            )
            if not success:
                value, kv = results[0]
                if value is None:
                    return None
        return 0

    def flush(self, path, fh):
        # Not required as FS is synchronous.
        pass

    def release(self, path, fh):
        self._close_file(fh)

    def fsync(self, path, fdatasync, fh):
        # Not required as FS is synchronous.
        pass


def main(mountpoint):
    FUSE(EtcdFS(), mountpoint, nothreads=True, foreground=True)

if __name__ == '__main__':
    main(sys.argv[1])
