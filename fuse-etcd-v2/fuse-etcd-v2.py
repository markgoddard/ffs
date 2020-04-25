#!/usr/bin/env python

import os
import os.path
import sys
import errno
import logging
import stat
import time

import etcd3
from fuse import FUSE, FuseOSError, LoggingMixIn, Operations
import json

import stm


logging.basicConfig(filename='fuse-etcd-v2.log', filemode='w', level=logging.DEBUG)


class File(object):

    def __init__(self, fd, path, flags):
        self.fd = fd
        self.path = path
        self.flags = flags


class Meta(object):
    """File metadata, stored in etcd as JSON."""

    attrs = {'atime', 'ctime', 'gid', 'mode', 'mtime', 'nlink', 'size', 'uid'}

    def __init__(self, atime, ctime, gid, mode, mtime, nlink, size, uid):
        self.atime = atime
        self.ctime = ctime
        self.gid = gid
        self.mode = mode
        self.mtime = mtime
        self.nlink = nlink
        self.size = size
        self.uid = uid

    @classmethod
    def from_json(cls, meta_json):
        return cls(**json.loads(meta_json))

    def to_json(self):
        return json.dumps({attr: getattr(self, attr) for attr in self.attrs})

    def to_stat(self):
        return {"st_" + attr: meta[attr] for attr in attrs}

    def is_dir(self):
        return (self.mode & stat.S_IFDIR) == stat.S_IFDIR

    def touch(self, atime=False, mtime=False, ctime=False):
        t = int(time.time())
        if mtime:
            self.mtime = t
        if atime:
            self.atime = t
        if ctime:
            self.ctime = t

    def to_attr(self):
        # As returned by getattr()
        return {"st_" + field: getattr(self, field) for field in self.attrs}


class EtcdFSV2(LoggingMixIn, Operations):
    def __init__(self):
        grpc_options = [
            ('grpc.max_receive_message_length', 100 * 1024 * 1024),
            ('grpc.max_send_message_length', 100 * 1024 * 1024),
        ]
        self.client = etcd3.client(grpc_options=grpc_options)
        # TODO: test client.
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
    def _get_meta_key(path):
        """Return the etcd key for metadata for a given path."""
        return os.path.join("meta", path.lstrip('/'))

    @staticmethod
    def _get_data_key(path):
        """Return the etcd key for data for a given path."""
        return os.path.join("data", path.lstrip('/'))

    @staticmethod
    def _get_path_from_meta_key(meta_key):
        return meta_key[5:]

    def _get_meta(self, path):
        meta_key = self._get_meta_key(path)
        meta, kv = self.client.get(meta_key)
        if meta is not None:
            meta = Meta.from_json(meta)
        return meta, kv

    def _get_data(self, path):
        data_key = self._get_data_key(path)
        return self.client.get(data_key)

    def _get_stm(self):
        return stm.STM(self.client)

    def _validate_path(self, path):
        for part in path.split(os.path.sep):
            if len(part) >= 256:
                raise FuseOSError(errno.ENAMETOOLONG)

    # Filesystem methods
    # ==================

    def init(self, path):
        assert path == '/'
        # Ensure root directory exists.
        self._ensure_file(path, 0o777 | stat.S_IFDIR, None)

    def access(self, path, mode):
        #meta, kv = self._get_meta(path)
        #file_mode = meta.mode
        #return mode & file_mode == file_mode
        # FIXME
        pass

    def chmod(self, path, mode):
        meta_key = self._get_meta_key(path)

        s = self._get_stm()

        @s.retried_transaction()
        def _chmod(s):
            meta = Meta.from_json(s.get(meta_key))
            # Update mode and ctime.
            meta.mode = mode
            meta.touch(ctime=True)
            s.put(meta_key, meta.to_json())

        _chmod()
        return 0

    def chown(self, path, uid, gid):
        meta_key = self._get_meta_key(path)

        s = self._get_stm()

        @s.retried_transaction()
        def _chown(s):
            meta = Meta.from_json(s.get(meta_key))
            # Update owner and ctime.
            meta.uid = uid
            meta.gid = gid
            meta.touch(ctime=True)
            s.put(meta_key, meta.to_json())

        _chown()
        return 0

    def getattr(self, path, fh=None):
        try:
            meta, kv = self._get_meta(path)
        except Exception as e:
            print e
            raise FuseOSError(errno.ENOENT)
        else:
            if meta is None and kv is None:
                raise FuseOSError(errno.ENOENT)
            else:
                return meta.to_attr()

    def readdir(self, path, fh):
        yield '.'
        yield '..'
        path = path.lstrip('/')
        for _, kv in self.client.get_prefix(self._get_meta_key(path), keys_only=True):
            file_path = self._get_path_from_meta_key(kv.key)
            if os.path.split(file_path)[0] == path:
                yield os.path.split(file_path)[-1]

    def readlink(self, path):
        raise NotImplementedError

    def mknod(self, path, mode, dev):
        raise NotImplementedError

    def rmdir(self, path):
        meta_key = self._get_meta_key(path)

        s = self._get_stm()

        @s.retried_transaction()
        def _rmdir(s):
            meta = Meta.from_json(s.get(meta_key))
            if not meta.is_dir():
                raise FuseOSError(errno.ENOTDIR)
            s.delete(meta_key)

        _rmdir()
        return 0

    def mkdir(self, path, mode):
        created = self._ensure_file(path, mode | stat.S_IFDIR, None)
        if not created:
            raise FuseOSError(errno.EEXIST)

    def statfs(self, path):
        raise NotImplementedError

    def unlink(self, path):
        meta_key = self._get_meta_key(path)
        data_key = self._get_data_key(path)

        s = self._get_stm()

        @s.retried_transaction()
        def _unlink(s):
            s.delete(meta_key)
            s.delete(data_key)

        _unlink()
        return 0

    def symlink(self, name, target):
        raise NotImplementedError

    def rename(self, old, new):
        meta_key = self._get_meta_key(old)
        data_key = self._get_data_key(old)
        new_meta_key = self._get_meta_key(new)
        new_data_key = self._get_data_key(new)

        s = self._get_stm()

        @s.retried_transaction(prefetch_keys=[meta_key, data_key])
        def _rename(s):
            meta = Meta.from_json(s.get(meta_key))
            data = s.get(data_key)
            meta.touch(ctime=True)
            s.delete(meta_key)
            s.delete(data_key)
            s.put(new_meta_key, meta.to_json())
            s.put(new_data_key, data)

        _rename()
        return 0

    def link(self, target, name):
        raise NotImplementedError

    def utimens(self, path, times=None):
        # TODO: update times
        pass

    # File methods
    # ============

    def _ensure_file(self, path, flags, content=""):
        self._validate_path(path)
        is_dir = (flags & stat.S_IFDIR) == stat.S_IFDIR
        size = 4096 if is_dir else len(content)
        uid = 1000 # mark
        gid = 1000 # mark
        meta = Meta(atime=0, ctime=0, gid=gid, mode=flags, mtime=0, nlink=1,
                    size=size, uid=uid)
        meta.touch(atime=True, ctime=True, mtime=True)
        meta_key = self._get_meta_key(path)
        data_key = self._get_data_key(path)
        success = [
            self.client.transactions.put(meta_key, meta.to_json()),
        ]
        compare = [
            self.client.transactions.create(meta_key) == 0,
        ]
        if not is_dir:
            success.append(self.client.transactions.put(data_key, content))
            compare.append(self.client.transactions.create(data_key) == 0)
        created, result = self.client.transaction(
            compare=compare,
            success=success,
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

        meta_key = self._get_meta_key(path)
        data_key = self._get_data_key(file.path)

        s = self._get_stm()

        @s.retried_transaction(prefetch_keys=[meta_key, data_key])
        def _read(s):
            value = s.get(data_key)
            if value is None:
                return None
            meta = Meta.from_json(s.get(meta_key))
            # Update accessed time.
            meta.touch(atime=True)
            s.put(meta_key, meta.to_json())
            # FIXME: Read only up to end?
            return value[offset:offset+length]

        return _read()

    def write(self, path, buf, offset, fh):
        # Handle get/update/put
        file = self._get_file(fh)
        assert path == file.path

        meta_key = self._get_meta_key(path)
        data_key = self._get_data_key(path)

        s = self._get_stm()

        @s.retried_transaction(prefetch_keys=[meta_key, data_key])
        def _write(s):
            meta = Meta.from_json(s.get(meta_key))
            data = s.get(data_key)
            # Update size and modified times.
            meta.size = max(meta.size, offset + len(buf))
            meta.touch(atime=True, ctime=True, mtime=True)
            data = data[:offset] + buf + data[offset + len(buf):]
            s.put(meta_key, meta.to_json())
            s.put(data_key, data)

        _write()
        return len(buf)

    def truncate(self, path, length, fh=None):
        meta_key = self._get_meta_key(path)
        data_key = self._get_data_key(path)

        s = self._get_stm()

        @s.retried_transaction(prefetch_keys=[meta_key, data_key])
        def _truncate(s):
            meta = Meta.from_json(s.get(meta_key))
            data = s.get(data_key)
            # Update size and modified times.
            meta.size = length
            meta.touch(atime=True, ctime=True, mtime=True)
            if len(data) >= length:
                data = data[:length]
            else:
                data = data + "\0" * (length - len(data))
            s.put(meta_key, meta.to_json())
            s.put(data_key, data)

        _truncate()
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
    FUSE(EtcdFSV2(), mountpoint, nothreads=True, foreground=True)


if __name__ == '__main__':
    main(sys.argv[1])
