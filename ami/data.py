import abc
import zmq
import time
import logging
try:
    import psana
except ImportError:
    psana = None
import numpy as np
from enum import Enum


logger = logging.getLogger(__name__)


class MsgTypes(Enum):
    Transition = 0
    Heartbeat = 1
    Datagram = 2
    Graph = 3


class DataTypes(Enum):
    Unknown = -1
    Unset = 0
    Scalar = 1
    Waveform = 2
    Image = 3
    List = 4

    @staticmethod
    def get_type(data):
        if data is None:
            return DataTypes.Unset
        elif isinstance(data, np.ndarray):
            if data.ndim == 1:
                return DataTypes.Waveform
            elif data.ndim == 2:
                return DataTypes.Image
            else:
                return DataTypes.Unknown
        elif isinstance(data, list):
            return DataTypes.List
        else:
            return DataTypes.Scalar


class Transitions(Enum):
    Allocate = 0
    Configure = 1
    Enable = 2
    Disable = 3


class Transition(object):
    def __init__(self, ttype, payload):
        self.ttype = ttype
        self.payload = payload

    def __str__(self):
        return "Transition:\n type: %s\n data: %s" % (self.ttype, self.payload)


class Datagram(object):
    def __init__(self, name, dtype, data=None):
        self.name = name
        self.dtype = dtype
        self.data = data

    def __str__(self):
        return "Datagram:\n dtype: %s\n data: %s" % (self.dtype, self.data)


class Message(object):
    def __init__(self, mtype, identity, payload):
        """
        Message container

        Args:
            mtype (MsgTypes): Message type

            identity (int): Message id number

            payload (dict): Message payload
        """
        self.mtype = mtype
        self.identity = identity
        self.payload = payload


class CollectorMessage(Message):
    def __init__(self, mtype, identity, heartbeat, version, payload):
        super(__class__, self).__init__(mtype, identity, payload)
        self.heartbeat = heartbeat
        self.version = version


class Source(abc.ABC):
    def __init__(self, idnum, num_workers, src_cfg, flags=None):
        """
        Args:
            idnum (int): Id number

            num_workers (int): Number of workers

            src_cfg (dict): Source configuration loaded from JSON file
        """

        self.idnum = idnum
        self.num_workers = num_workers
        self.interval = src_cfg['interval']
        self.init_time = src_cfg['init_time']
        self.config = src_cfg['config']
        self.requested_names = []
        self.flags = flags or {}

    @property
    @abc.abstractmethod
    def names(self):
        """
        Getter for the list of names of all data currently available from the source

        Returns:
            A list of names of all the currently available data from the source
        """
        pass

    def configure(self):
        """
        Constructs a properly formatted configure message

        Returns:
            An object of type `Message` which includes a list of
            names of the currently available detectors/data.
        """
        return Message(MsgTypes.Transition,
                       self.idnum,
                       Transition(Transitions.Configure, self.names))

    def event(self, timestamp, data):
        """
        Constructs a properly formatted event message

        Args:
            timestamp (int): timestamp of the event

            data (dict): the data of the event

        Returns:
            An object of type `Message` which includes the data for the event.
        """
        msg = Message(MsgTypes.Datagram, self.idnum, data)
        msg.timestamp = timestamp
        return msg

    def request(self, names):
        self.requested_names = names

    @abc.abstractmethod
    def events(self):
        """
        Generator which returns yields `Message` containing dictionary of data as payload.
        """
        pass


class PsanaSource(Source):

    def __init__(self, idnum, num_workers, src_cfg, flags=None):
        super(__class__, self).__init__(idnum, num_workers, src_cfg, flags)
        self.delimiter = ":"
        self.xtcdata_names = []
        if psana is not None:
            self.ds = psana.DataSource(self.config['filename'])
        else:
            raise NotImplementedError("psana is not available!")

    def _update_xtcdata_names(self, run):
        detinfo = run.detinfo
        self.xtcdata_names = []
        for (detname, det_xface_name), det_attr_list in detinfo.items():
            self.xtcdata_names += [self.delimiter.join((detname, det_xface_name, attr)) for attr in det_attr_list]
        return

    @property
    def names(self):
        return self.xtcdata_names

    def events(self):

        timestamp = 0
        time.sleep(self.init_time)

        while True:
            event = {}
            for run in self.ds.runs():
                self._update_xtcdata_names(run)
                self.detectors = {}  # psana Detector object cache
                yield self.configure()

                for evt in self.ds.events():
                    # FIXME: when we move to real timestamps we should use this line
                    # timestamp = evt.seq.timestamp()

                    for name in self.requested_names:

                        # each name is like "detname:drp_class_name:attrN"
                        namesplit = name.split(':')
                        detname = namesplit[0]

                        # if this is the first time we request a detector,
                        # make & cache the psana Detector object
                        if detname not in self.detectors:
                            self.detectors[detname] = run.Detector(detname)

                        # loop to the bottom level of the Det obj and get data
                        obj = self.detectors[detname]
                        for token in namesplit[1:]:
                            obj = getattr(obj, token)
                        event[name] = obj(evt)

                    yield self.event(timestamp, event)
                    timestamp += 1
                    time.sleep(self.interval)


class SimSource(Source):
    def __init__(self, idnum, num_workers, src_cfg, flags=None):
        super(__class__, self).__init__(idnum, num_workers, src_cfg, flags)
        self.count = 0
        self.synced = False
        if 'sync' in self.flags:
            self.ctx = zmq.Context()
            self.ts_src = self.ctx.socket(zmq.REQ)
            self.ts_src.connect(self.flags['sync'])
            self.synced = True

    @property
    def timestamp(self):
        if self.synced:
            self.ts_src.send_string("ts")
            return self.ts_src.recv_pyobj()
        else:
            self.count += 1
            return self.num_workers * self.count + self.idnum


class RandomSource(SimSource):
    def __init__(self, idnum, num_workers, src_cfg, flags=None):
        super(__class__, self).__init__(idnum, num_workers, src_cfg, flags)
        np.random.seed([idnum])

    @property
    def names(self):
        return list(self.config.keys())

    def events(self):
        time.sleep(self.init_time)
        yield self.configure()
        while True:
            event = {}
            for name, config in self.config.items():
                if name in self.requested_names:
                    if config['dtype'] == 'Scalar':
                        value = config['range'][0] + (config['range'][1] - config['range'][0]) * np.random.rand(1)[0]
                        if config.get('integer', False):
                            event[name] = int(value)
                        else:
                            event[name] = value
                    elif config['dtype'] == 'Waveform' or config['dtype'] == 'Image':
                        event[name] = np.random.normal(config['pedestal'], config['width'], config['shape'])
                    else:
                        logger.warn("DataSrc: %s has unknown type %s", name, config['dtype'])
            yield self.event(self.timestamp, event)
            time.sleep(self.interval)


class StaticSource(SimSource):
    def __init__(self, idnum, num_workers, src_cfg, flags=None):
        super(__class__, self).__init__(idnum, num_workers, src_cfg, flags)
        self.bound = np.inf

        if 'bound' in src_cfg:
            self.bound = src_cfg['bound']

    @property
    def names(self):
        return list(self.config.keys())

    def events(self):
        count = 0
        time.sleep(self.init_time)
        yield self.configure()
        while True:
            event = {}
            for name, config in self.config.items():
                if name in self.requested_names:
                    if config['dtype'] == 'Scalar':
                        event[name] = 1
                    elif config['dtype'] == 'Waveform' or config['dtype'] == 'Image':
                        event[name] = np.ones(config['shape'])
                    else:
                        logger.warn("DataSrc: %s has unknown type %s", name, config['dtype'])
            count += 1
            yield self.event(self.timestamp, event)
            if count >= self.bound:
                break
            time.sleep(self.interval)
