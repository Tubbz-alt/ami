import time
try:
    import psana
except ImportError:
    psana = None
import numpy as np
from enum import Enum


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

    @staticmethod
    def get_type(data):
        if isinstance(data, np.ndarray):
            if data.ndim == 1:
                return DataTypes.Waveform
            elif data.ndim == 2:
                return DataTypes.Image
            else:
                return DataTypes.Unknown
        else:
            return DataTypes.Scalar


class Strategies(Enum):
    Sum = "Sum"
    Avg = "Average"
    Pick1 = "Pick1"


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
    def __init__(self, name, dtype, data=None, weight=0):
        self.name = name
        self.dtype = dtype
        self.data = data
        self.weight = weight

    def __str__(self):
        return "Datagram:\n dtype: %s\n data: %s" % (self.dtype, self.data)


class Message(object):
    def __init__(self, mtype, identity, payload):
        self.mtype = mtype
        self.identity = identity
        self.payload = payload


class CollectorMessage(Message):
    def __init__(self, mtype, identity, heartbeat, payload):
        super(__class__, self).__init__(mtype, identity, payload)
        self.heartbeat = heartbeat


class PsanaSource(object):
    def __init__(self, idnum, num_workers, src_cfg):
        self.idnum = idnum
        self.num_workers = num_workers
        self.interval = src_cfg['interval']
        self.init_time = src_cfg['init_time']
        self.config = src_cfg['config']
        self.ds = psana.DataSource(self.config['filename'])

    def partition(self):
        dets = []
        for run in self.ds.runs():
            detinfo = run.detinfo
            for detname, det_xface_dict in detinfo.items():
                # need this loop when we send the GUI det xfaces and attributes
                # for det_xface_name,det_xface_attrs in det_xface_dict.items():
                datatype = DataTypes.Waveform  # FIXME: should only need this when we get an event
                dets.append((detname, datatype))
        return dets

    def events(self):
        timestamp = 0
        time.sleep(self.init_time)
        while True:
            event = []
            if psana is None:
                print("psana is not available!")
                break
            for evt in self.ds.events():
                for dgram in evt._dgrams:
                    timestamp = dgram.seq.timestamp()
                    event.append(Datagram("xppcspad", DataTypes.Waveform, evt.xppcspad.raw.raw))
                    msg = Message(MsgTypes.Datagram, self.idnum, event)
                    msg.timestamp = timestamp
                    yield msg
                    time.sleep(self.interval)


class RandomSource(object):
    def __init__(self, idnum, num_workers, src_cfg):
        np.random.seed([idnum])
        self.idnum = idnum
        self.num_workers = num_workers
        self.interval = src_cfg['interval']
        self.init_time = src_cfg['init_time']
        self.config = src_cfg['config']

    def partition(self):
        return [(key, getattr(DataTypes, value['dtype'])) for key, value in self.config.items()]

    def events(self):
        count = 0
        time.sleep(self.init_time)
        while True:
            event = []
            for name, config in self.config.items():
                if config['dtype'] == 'Scalar':
                    event.append(
                        Datagram(
                            name,
                            getattr(DataTypes, config['dtype']),
                            config['range'][0] + (config['range'][1] - config['range'][0]) * np.random.rand(1)[0]
                        )
                    )
                elif config['dtype'] == 'Waveform' or config['dtype'] == 'Image':
                    event.append(
                        Datagram(
                            name,
                            getattr(DataTypes, config['dtype']),
                            np.random.normal(config['pedestal'], config['width'], config['shape'])
                        )
                    )
                else:
                    print("DataSrc: %s has unknown type %s", name, config['dtype'])
            count += 1
            msg = Message(MsgTypes.Datagram, self.idnum, event)
            msg.timestamp = self.num_workers * count + self.idnum
            yield msg
            time.sleep(self.interval)


class StaticSource(object):
    def __init__(self, idnum, num_workers, src_cfg):
        self.idnum = idnum
        self.num_workers = num_workers
        self.interval = src_cfg['interval']
        self.init_time = src_cfg['init_time']
        self.config = src_cfg['config']
        self.bound = np.inf

        if 'bound' in src_cfg:
            self.bound = src_cfg['bound']

    def partition(self):
        return [(key, getattr(DataTypes, value['dtype'])) for key, value in self.config.items()]

    def events(self):
        count = 0
        time.sleep(self.init_time)
        while True:
            event = []
            for name, config in self.config.items():
                if config['dtype'] == 'Scalar':
                    event.append(
                        Datagram(
                            name,
                            getattr(DataTypes, config['dtype']),
                            1
                        )
                    )
                elif config['dtype'] == 'Waveform' or config['dtype'] == 'Image':
                    event.append(
                        Datagram(
                            name,
                            getattr(DataTypes, config['dtype']),
                            np.ones(config['shape'])
                        )
                    )
                else:
                    print("DataSrc: %s has unknown type %s", name, config['dtype'])
            count += 1
            msg = Message(MsgTypes.Datagram, self.idnum, event)
            msg.timestamp = self.num_workers * count + self.idnum
            yield msg
            if count >= self.bound:
                break
            time.sleep(self.interval)
