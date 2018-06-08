
import sys
import abc
import zmq
import threading
from enum import IntEnum

from ami.data import MsgTypes, Message, CollectorMessage, DataTypes, Datagram


class Ports(IntEnum):
    Comm = 5555
    Graph = 5556
    Collector = 5557


class Store(object):
    """
    This class is a key value that for holding Datagrams
    """

    def __init__(self):
        self._store = {}

    def create(self, name, datatype=DataTypes.Unset):
        if name in self._store:
            raise ValueError("result named %s already exists in ResultStore"%name)
        else:
            self._store[name] = Datagram(name, datatype)
            self._updated[name] = False

    def get_dgram(self, name):
        return self._store[name]

    @property
    def namespace(self):
        ns = {"store": self}
        for k in self._store.keys():
            ns[k] = self._store[k].data
        return ns

    def get(self, name):
        return self._store[name].data

    def put(self, name, data):
        datatype = DataTypes.get_type(data)
        if name in self._store:
            if datatype == self._store[name].dtype or self._store[name].dtype == DataTypes.Unset:
                self._store[name].dtype = datatype
                self._store[name].data = data
            else:
                raise TypeError("type of new result (%s) differs from existing"
                                " (%s)"%(datatype, self._store[name].dtype))
        else:
            self._store[name] = Datagram(name, datatype, data)

        self._updated[name] = True

    def clear(self):
        self._store = {}


class ResultStore(Store):
    """
    This class is a AMI /graph node that collects results
    from a single process and has the ability to send them
    to another (via zeromq). The sending end point is typically
    a Collector object.
    """

    def __init__(self, addr, ctx=None):
        super(__class__, self).__init__()
        self._updated = {}
        if ctx is None:
            self.ctx = zmq.Context()
        else:
            self.ctx = ctx
        self.collector = self.ctx.socket(zmq.PUSH)
        self.collector.connect(addr)

    def collect(self, eb_id, heartbeat):
        for name, result in self._store.items():
            if self._updated[name]:
                self.send(CollectorMessage(MsgTypes.Datagram, eb_id, heartbeat, result))
                self._updated[name] = False
        self.send(CollectorMessage(MsgTypes.Heartbeat, eb_id, heartbeat, None))

    def send(self, msg):
        self.collector.send_pyobj(msg)

    def message(self, mtype, payload):
        msg = Message(mtype, payload)
        self.send(msg)

    def is_ready(self, name):
        if name in self._store.keys():
            return self._updated[name]
        else:
            return False

class EventBuilder(object):

    def __init__(self, depth, addr, ctx=None):
        self.depth = depth
        # using a dict because it is random access instead of a sequential list
        self.pending = {}
        #for _ in range(depth):
        #    self.pending.append(ResultStore(addr, ctx))

    

    


class Collector(abc.ABC):
    """
    This class gathers (via zeromq) results from many
    ResultsStores. But rather than use gather, it employs
    an async send/recieve pattern.
    """

    def __init__(self, addr, ctx=None):
        if ctx is None:
            self.ctx = zmq.Context()
        else:
            self.ctx = ctx
        self.poller = zmq.Poller()
        self.collector = self.ctx.socket(zmq.PULL)
        self.collector.bind(addr)
        self.poller.register(self.collector, zmq.POLLIN)
        self.handlers = {}
        return

    def register(self, sock, handler):
        self.handlers[sock] = handler
        self.poller.register(sock, zmq.POLLIN)

    def unregister(self, sock):
        if sock in self.handlers:
            del self.handlers[sock]
            self.poller.unregister(sock)

    def recv(self):
        return self.collector.recv_pyobj()

    @abc.abstractmethod
    def process_msg(self, msg):
        return

    def run(self):
        while True:
            for sock, flag in self.poller.poll():
                if flag != zmq.POLLIN:
                    continue
                if sock is self.collector:
                    msg = self.recv()
                    self.process_msg(msg)
                elif sock in self.handlers:
                    self.handlers[sock]()
