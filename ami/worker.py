import re
import os
import sys
import zmq
import time
import json
import shutil
import tempfile
import argparse
import multiprocessing as mp
from ami.graph import Graph, GraphConfigError, GraphRuntimeError
from ami.comm import Ports, Collector, ResultStore
from ami.data import MsgTypes, DataTypes, Transitions, Occurrences, Message, Datagram, Transition, StaticSource

class Worker(object):
    def __init__(self, idnum, src, collector_addr, graph_addr):

        """
        idnum : int
            a unique integer identifying this worker
        src : object
            object with an events() method that is an iterable (like psana.DataSource)
        """

        self.idnum = idnum
        self.src = src
        self.ctx = zmq.Context()
        self.store = ResultStore(collector_addr, self.ctx)

        # >>> NON PYTHONBACKEND
        self.graph = Graph(self.store)

        self.graph_comm = self.ctx.socket(zmq.SUB)
        #self.graph_comm.setsockopt_string(zmq.SUBSCRIBE, "graph")
        self.graph_comm.setsockopt_string(zmq.SUBSCRIBE, "")
        self.graph_comm.connect(graph_addr)
        self.requests = []

        self.hb_received = False

    def run(self):
        sources = []
        partition = self.src.partition()
        self.store.message(MsgTypes.Transition, 
                           Transition(Transitions.Allocate, partition))
        for name, dtype in partition:
            self.store.create(name, dtype)
            sources.append(name)

        for msg in self.src.events():
            # check to see if the graph has been reconfigured after update
            if msg.mtype == MsgTypes.Occurrence and msg.payload == Occurrences.Heartbeat:
                self.store.put('hb_count', msg.hb_count)
                self.hb_received = True
                new_graph = None
                while True:
                    try:
                        topic = self.graph_comm.recv_string(flags=zmq.NOBLOCK)
                        payload = self.graph_comm.recv_pyobj()
                        if topic == "graph":
                            new_graph = payload
                        elif topic == "request":
                            self.requests.append(Request(self.store,*payload))
                        else:
                            print("worker%d: No handler for received topic: %s"%(self.idnum, topic))
                    except zmq.Again:
                        break
                if new_graph is not None:

                    # >>> NON PYTHONBACKEND
                    self.graph.update(new_graph)

                    print("worker%d: Received new configuration"%self.idnum)


                    # >>> NON PYTHONBACKEND
                    # >>> TODO figure out how to check graph
                    try:
                        self.graph.configure(sources)
                        print("worker%d: Configuration complete"%self.idnum)
                    except GraphConfigError as graph_err:
                        print("worker%d: Configuration failed reverting to previous config:"%self.idnum, graph_err)
                        # if this fails we just die
                        self.graph.revert()

                    self.new_graph_available = False
                if new_graph is not None:
                    self.store.message(MsgTypes.Graph, new_graph)
                self.store.send(msg)
            elif msg.mtype == MsgTypes.Datagram:
                # clear old values from the store
                #self.store.clear()
                for dgram in msg.payload:
                    if self.hb_received:
                        self.store.put(dgram.name, dgram.data)

                try:
                    self.graph.execute()
                except GraphRuntimeError as graph_err:
                    print("worker%s: Failure encountered executing graph:"%self.idnum, graph_err)
                    return 1

                self.store.collect()
                for r in self.requests:
                    if (r.update()):
                        self.requests.remove(r)
                        print(self.store.get('cspad_avg_3').shape)
            else:
                self.store.send(msg)


class NodeCollector(Collector):
    def __init__(self, node, num_workers, collector_addr, downstream_addr):
        super(__class__, self).__init__(collector_addr)
        self.node = node
        self.counts = { MsgTypes.Transition: 0, MsgTypes.Occurrence: 0 }
        self.num_workers = num_workers
        self.store = ResultStore(downstream_addr, self.ctx)

    def process_msg(self, msg):
        if msg.mtype == MsgTypes.Transition:
            self.counts[MsgTypes.Transition] += 1
            if self.counts[MsgTypes.Transition] == self.num_workers:
                if msg.payload.ttype == Transitions.Allocate:
                    for name, dtype in msg.payload.payload:
                        self.store.create(name, dtype)
                self.store.send(msg)
                self.counts[MsgTypes.Transition] = 0
        elif msg.mtype == MsgTypes.Occurrence:
            self.counts[MsgTypes.Occurrence] += 1
            if self.counts[MsgTypes.Occurrence] == self.num_workers:
                if msg.payload == Occurrences.Heartbeat:
                    self.store.collect()
                self.store.send(msg)
                self.counts[MsgTypes.Occurrence] = 0
        elif msg.mtype == MsgTypes.Datagram:
            self.store.put(msg.payload.name, msg.payload.data)
        elif msg.mtype == MsgTypes.Graph:
            self.strategies = Graph.extract_collection_strategies(msg.payload)

def run_worker(num, source, collector_addr, graph_addr):

    print('Starting worker # %d, sending to collector at %s' % (num, collector_addr))

    if source[0] == 'static':
        try:
            with open(source[1], 'r') as cnf:
                src_cfg = json.load(cnf)
        except OSError as os_exp:
            print("worker%03d: problem opening json file:"%num, os_exp)
            return 1
        except json.decoder.JSONDecodeError as json_exp:
            print("worker%03d: problem parsing json file (%s):"%(num, source[1]), json_exp)
            return 1

        src = StaticSource(num, 
                           src_cfg['interval'], 
                           src_cfg['heartbeat'], 
                           src_cfg["init_time"], 
                           src_cfg['config'])
    else:
        print("worker%03d: unknown data source type:"%num, source[0])
        return 1
    worker = Worker(num, src, collector_addr, graph_addr)
    return worker.run()


def run_collector(node_num, num_workers, collector_addr, upstream_addr):
    print('Starting collector on node # %d' % node_num)
    collector = NodeCollector(node_num, num_workers, collector_addr, upstream_addr)
    return collector.run()


def main():
    parser = argparse.ArgumentParser(description='AMII Worker/Collector App')

    parser.add_argument(
        '-H',
        '--host',
        default='localhost',
        help='hostname of the AMII Manager (default: localhost)'
    )

    parser.add_argument(
        '-p',
        '--port',
        type=int,
        default=Ports.Comm,
        help='port for GUI-Manager communication (default: %d)'%Ports.Comm
    )

    parser.add_argument(
        '-g',
        '--graph',
        type=int,
        default=Ports.Graph,
        help='port for graph communication (default: %d)'%Ports.Graph
    )

    parser.add_argument(
        '-c',
        '--collector',
        type=int,
        default=Ports.Collector,
        help='port for final collector (default: %d)'%Ports.Collector
    )

    parser.add_argument(
        '-n',
        '--num-workers',
        type=int,
        default=1,
        help='number of worker processes (default: 1)'
    )

    parser.add_argument(
        '-N',
        '--node-num',
        type=int,
        default=0,
        help='node identification number (default: 0)'
    )

    parser.add_argument(
        'source',
        metavar='SOURCE',
        help='data source configuration (exampes: static://test.json, psana://exp=xcsdaq13:run=14)'
    )

    args = parser.parse_args()
    ipcdir = tempfile.mkdtemp()
    collector_addr = "ipc://%s/node_collector"%ipcdir
    upstream_addr = "tcp://%s:%d"%(args.host, args.collector)
    graph_addr = "tcp://%s:%d"%(args.host, args.graph)
    comm_addr = "tcp://%s:%d"%(args.host, args.port)

    procs = []
    failed_worker = False

    try:
        src_url_match = re.match('(?P<prot>.*)://(?P<body>.*)', args.source)
        if src_url_match:
            src_cfg = src_url_match.groups()
        else:
            print("Invalid data source config string:", args.source)
            return 1

        for i in range(args.num_workers):
            proc = mp.Process(
                name='worker%03d-n%03d'%(i, args.node_num),
                target=run_worker,
                args=(i, src_cfg, collector_addr, graph_addr)
            )
            proc.daemon = True
            proc.start()
            procs.append(proc)

        collector_proc = mp.Process(
            name='manager-n%03d'%args.node_num,
            target=run_collector,
            args=(args.node_num, args.num_workers, collector_addr, upstream_addr)
        )
        collector_proc.daemon = True
        collector_proc.start()
        procs.append(collector_proc)

        for proc in procs:
            proc.join()
            if proc.exitcode == 0:
                print('%s exited successfully'%proc.name)
            else:
                failed_worker = True
                print('%s exited with non-zero status code: %d'%(proc.name, proc.exitcode))

        # return a non-zero status code if any workerss died
        if failed_worker:
            return 1

        return 0
    except KeyboardInterrupt:
        print("Worker killed by user...")
        return 0
    finally:
        if ipcdir is not None and os.path.exists(ipcdir):
            shutil.rmtree(ipcdir)


if __name__ == '__main__':
    sys.exit(main()) 
