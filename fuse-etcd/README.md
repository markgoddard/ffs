# FUSE Etcd

`fuse-etcd.py`

A very basic FUSE filesystem built using the [etcd](https://etcd.io/) key value
store as a backend. This driver uses the same `fusepy` library used by the FUSE
passthrough driver.

It's (over-)simple - paths are keys, file content in values. There's no
metadata (permissions, ownership, timestamps, etc.). Directories are just files
containing the magic string `__DIRECTORY__`.

Although there are clearly many shortcomings to this filesystem, some effort
has been made to provide consistency between multiple clients. This is
implemented using `etcd's` transaction support.

A very minimal set of tests is available in `test-fuse-etcd.py`.

## Usage

```
docker run -d --net=host --volume=etcd:/etcd-data --name etcd quay.io/coreos/etcd:latest /usr/local/bin/etcd --data-dir=/etcd-data --name etcd
virtualenv venv
venv/bin/pip install -r requirements.txt
venv/bin/python fuse-etcd.py <mountpoint>
ls <mountpoint>
```
