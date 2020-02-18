import contextlib
import functools
import json
import time

import etcd3


class Conflict(Exception):
    pass


class AlreadyInTransaction(Exception):
    pass


class STM(object):
    """Software Transactional Memory (STM) using etcd."""

    def __init__(self, client):
        self.client = client
        self.rset = {}
        self.wset = {}
        self.conflicts = {}

    def get(self, key):
        if key in self.rset:
            return self.rset[key][0]
        value, kv = self.client.get(key)
        self.rset[key] = value, kv
        if value is not None:
            self.conflicts[key] = kv
        else:
            # TODO: check that key still does not exist?
            pass
        return value

    def put(self, key, value):
        self.wset[key] = value
        self.rset[key] = value, None

    def delete(self, key):
        self.put(key, None)

    @contextlib.contextmanager
    def transaction(self, prefetch_keys=None):
        if self.conflicts:
            raise AlreadyInTranscation()

        if prefetch_keys:
            self.prefetch(prefetch_keys)
        try:
            yield self
        except:
            self.reset()
            raise
        else:
            self.commit()

    def prefetch(self, prefetch_keys):
        to_fetch = set(prefetch_keys) - set(self.rset)
        if not to_fetch:
            return

        success = [self.client.transactions.get(key) for key in to_fetch]
        success, result = self.client.transaction(compare=[],
                                                  success=success,
                                                  failure=[])
        for value, kv in result[0]:
            self.rset[kv.key] = value, kv
            if value is not None:
                self.conflicts[kv.key] = kv
        assert success

    def reset(self):
        self.rset = {}
        self.wset = {}
        self.conflicts = {}

    def commit(self):
        compare = []
        success = []
        failure = []
        for key, kv in self.conflicts.items():
            compare.append(self.client.transactions.version(key) == kv.version)
        for key, value in self.wset.items():
            if value is None:
                success.append(self.client.transactions.delete(key))
            else:
                success.append(self.client.transactions.put(key, value))
        for key, value in self.rset.items():
            failure.append(self.client.transactions.get(key))

        success, result = self.client.transaction(compare=compare,
                                                  success=success,
                                                  failure=failure)

        if not success:
            self.reset()
            # Populate read set and conflicts with current value of all reads.
            for value, kv in result[0]:
                self.rset[kv.key] = value, kv
                self.conflicts[kv.key] = kv
            raise Conflict()

    def retried_transaction(self, retries=10, interval=0, *args, **kwargs):

        def _decorator(func):

            @functools.wraps(func)
            def _retried():
                for attempt in range(retries):
                    try:
                        with self.transaction(*args, **kwargs):
                            return func(self)
                    except Conflict:
                        if attempt == retries - 1:
                            raise
                        print "got conflict, retrying"
                        if interval:
                            time.sleep(interval)
                        continue

            return _retried

        return _decorator


if __name__ == "__main__":
    while True:
        stm = STM(etcd3.client())

        @stm.retried_transaction(prefetch_keys=['counter'])
        def increment(stm):
            counter = stm.get("counter")
            if counter is None:
                counter = "0"
            counter = json.loads(counter)
            print "counter", counter
            stm.put("counter", json.dumps(counter + 1))

        increment()
        time.sleep(0.1)
