import asyncio
import pytest
import zmq
import time
import multiprocessing as mp
from ami.client import GraphAddress
from ami.client.flowchart import MessageBroker
import ami.client.flowchart_messages as fcMsgs
from ami.flowchart.Flowchart import Flowchart
from ami.flowchart.NodeLibrary import SourceLibrary
from ami.nptype import Array2d
from collections import OrderedDict


class BrokerHelper:
    def __init__(self, ipcdir, comm):
        # we are in a forked process so create a new event loop (needed in some cases).
        self.loop = asyncio.new_event_loop()
        # set this new event loop as the default one so zmq picks it up
        asyncio.set_event_loop(self.loop)
        self.broker = MessageBroker("", "", ipcdir=ipcdir)
        self.comm = comm
        self.loop.run_until_complete(self.run())
        self.loop.close()

    async def run(self):
        await asyncio.gather(self.broker.run(),
                             self.loop.run_in_executor(None, self.communicate))

    def communicate(self):
        while True:
            name = self.comm.recv()
            self.comm.send(getattr(self.broker, name))

    @staticmethod
    def execute(ipcdir, comm):
        return BrokerHelper(ipcdir, comm)


class BrokerProxy:
    def __init__(self, comm):
        self.comm = comm

    def __getattr__(self, name):
        self.comm.send(name)
        return self.comm.recv()


@pytest.fixture(scope='function')
def broker(ipc_dir):
    try:
        from pytest_cov.embed import cleanup_on_sigterm
        cleanup_on_sigterm()
    except ImportError:
        pass

    parent_comm, child_comm = mp.Pipe()
    # start the manager process
    proc = mp.Process(
        name='broker',
        target=BrokerHelper.execute,
        args=(ipc_dir, child_comm),
        daemon=False
    )
    proc.start()

    yield BrokerProxy(parent_comm)

    # cleanup the manager process
    proc.terminate()
    proc.join(1)
    return proc.exitcode


def test_broker_sub(broker):
    ctx = zmq.Context()
    socket = ctx.socket(zmq.XPUB)
    socket.connect(broker.broker_sub_addr)
    # wait for the subscriber to connect
    assert socket.recv_string() == '\x01'

    name = "Projection"
    msg = fcMsgs.CreateNode(name, "Projection")
    socket.send_string(name, zmq.SNDMORE)
    socket.send_pyobj(msg)

    # check that broker msgs are empty
    msgs = broker.msgs
    assert not msgs

    # send a node close msg
    msg = fcMsgs.CloseNode()
    socket.send_string(name, zmq.SNDMORE)
    socket.send_pyobj(msg)

    # wait to see if the broker msgs are updated
    start = time.time()
    while not msgs:
        end = time.time()
        if end - start > 10:
            assert False, "Timeout waiting for broker update"
        msgs = broker.msgs
    # check the msg
    assert name in msgs
    assert isinstance(msgs[name], fcMsgs.CloseNode)


@pytest.mark.parametrize('start_ami', ['static'], indirect=True)
def test_source_library(complex_graph_file, start_ami):
    comm_handler = start_ami
    comm_handler.load(complex_graph_file)

    start = time.time()
    while comm_handler.graphVersion != comm_handler.featuresVersion:
        end = time.time()
        if end - start > 10:
            raise TimeoutError

    sources = comm_handler.sources
    source_library = SourceLibrary()

    for source, node_type in sources.items():
        root, *_ = source.split(':')
        source_library.addNodeType(source, node_type, [[root]])

    assert source_library.sourceList == {'cspad': Array2d, 'delta_t': int,
                                         'heartbeat': int, 'laser': int, 'timestamp': int}
    assert source_library.getSourceType('cspad') == Array2d

    try:
        source_library.addNodeType('cspad', Array2d, [[]])
    except Exception:
        pass

    try:
        source_library.getSourceType('')
    except Exception:
        pass

    assert source_library.getSourceTree() == OrderedDict([('delta_t', OrderedDict([('delta_t', 'delta_t')])),
                                                          ('cspad', OrderedDict([('cspad', 'cspad')])),
                                                          ('laser', OrderedDict([('laser', 'laser')])),
                                                          ('timestamp', OrderedDict([('timestamp', 'timestamp')])),
                                                          ('heartbeat', OrderedDict([('heartbeat', 'heartbeat')]))])

    labelTree = OrderedDict([('delta_t', [('delta_t', "<class 'int'>")]),
                             ('cspad', [('cspad', "<class 'ami.nptype.Array2d'>")]),
                             ('laser', [('laser', "<class 'int'>")]),
                             ('timestamp', [('timestamp', "<class 'int'>")]),
                             ('heartbeat', [('heartbeat', "<class 'int'>")])])

    assert source_library.getLabelTree() == labelTree
    assert source_library.getLabelTree() == labelTree


@pytest.mark.parametrize('start_ami', ['static'], indirect=True)
def test_editor(qtbot, broker, start_ami):

    comm_handler = start_ami
    time.sleep(1)
    sources = comm_handler.sources

    source_library = SourceLibrary()
    for source, node_type in sources.items():
        root, *_ = source.split(':')
        source_library.addNodeType(source, node_type, [[root]])

    graphmgr = GraphAddress("graph", comm_handler._addr)

    fc = Flowchart(broker_addr=broker.broker_sub_addr,
                   graphmgr_addr=graphmgr,
                   node_addr=broker.node_addr,
                   checkpoint_addr=broker.checkpoint_pub_addr,
                   source_library=source_library)

    qtbot.addWidget(fc.widget())

    fc.createNode('Roi')
    nodes = fc.nodes()
    assert 'Roi.0' in nodes
