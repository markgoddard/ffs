## FUSE passthrough

`fuse-passthrough.py`

A passthrough FUSE filesystem, built using fusepy. Code taken from [Stavros
Korokithakis](https://github.com/skorokithakis/python-fuse-sample).

This is really just used as a basic example of how to write a FUSE filesystem
in Python. File system operations at the mount point are passed through to
another location in the file system. I've added the `LoggingMixIn` and a file
logger so that we can see which operations the driver is performing as it is
used.

### Usage

```
virtualenv venv
venv/bin/pip install -r requirements.txt
venv/bin/python fuse-passthrough.py <source> <destination>
ls <destination>
```

### What happens when I...?

Using this file system we can investigate what happens under the hood when
performing various tasks. We'll use the `LoggingMixIn`.

#### Mount the file system

Mount my home directory at `/mnt/passthrough`:

`venv/bin/python fuse-passthrough.py ~/ /mnt/passthrough

We get the following calls:

* `access('/', 4)`
* `getattr('/.Trash', None)`
* `getattr('/.Trash-1000', None)`

We are checking if the caller has access to the file system root directory,
then if two special directories used for implementing a recycling bin. In this
case they do not, and an `OSError` is raised with `errno` 2.

#### Change to the root file system directory

`cd /mnt/passthrough`

We get the following calls:

* `getattr('/', None)`
* `access('/', 1)`

This time `getattr` returns successfully, and returns a `stat` dict:

`{'st_ctime': 1582475059.1262531, 'st_mtime': 1582475059.1262531, 'st_nlink': 64, 'st_mode': 16877, 'st_size': 4096, 'st_gid': 1000, 'st_uid': 1000, 'st_atime': 1582475228.703084}`

This is based on the Linux `struct stat`.

#### List the root file system directory

`ls`

We get the following calls:

* `getattr('/', None)`
* `access('/', 1)`
* `opendir('/')`
* `readdir('/', 0)`
* For every file in the directory:
  * `getattr('/file', None)`
* `releasedir('/', 0)`

This starts in the same way as the change to the directory. Next the directory
is opened, and `readdir` returns a list of every file in the directory
(including the special files '.' and '..'). For each of these files, we get a
`getattr` which returns a `stat` dict as we saw previously. Finally, the
directory is released via `releasedir`.

#### Create a file

`echo foo > bar`

We get the following calls:

* `getattr('/bar', None)`
* `create('/bar', 33204)`
* `getattr('/bar', 5)`
* `flush('/bar', 5)`
* `getxattr('/bar', 'security.capability')`
* `write('/bar', 'foo', 0, 5)`
* `flush('/bar', 5)`
* `release('/bar', 5)`

Here we see the use of the `create` method to create the file, `flush` to flush
the file system contents, `write` to write to a file, and `release` to release
a file handle. `getxattr` is called with `security.capability` which is used
for [executable
capabilities](http://man7.org/linux/man-pages/man7/capabilities.7.html).

#### Read a file

`cat bar`

We get the following calls:

* `getattr('/bar', None)`
* `open('/bar', 5)`
* `read('/bar', 4096, 0, 5)`
* `getattr('/bar', 5)`
* `flush('/bar', 5)`
* `release('/bar', 5)`

Similar to our write, but this time we use the `read` method.
