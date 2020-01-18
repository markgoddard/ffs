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
