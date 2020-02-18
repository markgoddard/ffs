# FUSE Etcd v2

`fuse-etcd-v2.py`

A FUSE filesystem built using the [etcd](https://etcd.io/) key value
store as a backend. This driver is an improvement on the FUSE Etcd driver,
adding support for metadata.

A very minimal set of tests is available in `test-fuse-etcd-v2.py`.

This filesystem builds on [fuse-etcd](../fuse-etcd), with a few changes. The
storage of filesystem data is separated from metadata under a separate key
hierarchy, which allows us to provide file metadata. Metadata is stored as a
JSON-encoded string, and is based on the `stat` fields used by the `getattr`
method.

Now that metadata and data are stored under separate keys, it is important to
ensure they are updated consistently. To achieve this we use etcd transactions,
with Software Transactional Memory (STM) as an abstraction on top of this.
The STM code is loosely based on the example STM provided in the [etcd
source](https://github.com/etcd-io/etcd/blob/master/clientv3/concurrency/stm.go).

## Usage

```
docker run -d --net=host --volume=etcd:/etcd-data --name etcd quay.io/coreos/etcd:latest /usr/local/bin/etcd --data-dir=/etcd-data --name etcd
virtualenv venv
venv/bin/pip install -r requirements.txt
venv/bin/python fuse-etcd-v2.py <mountpoint>
ls <mountpoint>
```
