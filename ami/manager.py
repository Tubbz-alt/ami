#!/usr/bin/env python
import re
import sys
import zmq
import dill
import logging
import argparse
from ami import LogConfig
from ami.comm import Ports, Collector, Store
from ami.data import MsgTypes, Transitions
from ami.graphkit_wrapper import Graph


logger = logging.getLogger(__name__)


class Manager(Collector):
    """
    An AMI graph Manager is the control point for an
    active "tree" of workers. It is the final collection
    point for all results, broadcasts those results to
    clients (e.g. plots/GUIs), and handles requests for
    configuration changes to the graph.
    """

    def __init__(self,
                 num_workers,
                 num_nodes,
                 results_addr,
                 graph_addr,
                 comm_addr,
                 msg_addr,
                 info_addr,
                 export_addr=None):
        """
        protocol right now only tells you how to communicate with workers
        """
        super().__init__(results_addr)
        self.num_workers = num_workers
        self.num_nodes = num_nodes
        self.heartbeats = {}
        self.partition = {}
        self.feature_stores = {}
        self.feature_req = re.compile("(?P<type>fetch):(?P<name>.*)")
        self.graphs = {}
        self.versions = {}
        self.purged = set()
        self.global_cmds = {"list_graphs"}
        self.no_auto_create_cmds = {"create_graph", "destroy_graph"}

        if export_addr is None:
            self.export = None
        else:
            self.export = self.ctx.socket(zmq.PUB)
            self.export.bind(export_addr)

        self.comm = self.ctx.socket(zmq.REP)
        self.comm.bind(comm_addr)
        self.register(self.comm, self.client_request)
        self.graph_comm = self.ctx.socket(zmq.XPUB)
        self.graph_comm.setsockopt(zmq.XPUB_VERBOSE, True)
        self.graph_comm.bind(graph_addr)
        self.register(self.graph_comm, self.graph_request)
        self.info_comm = self.ctx.socket(zmq.PUB)
        self.info_comm.bind(info_addr)
        self.node_msg_comm = self.ctx.socket(zmq.PULL)
        self.node_msg_comm.bind(msg_addr)
        self.register(self.node_msg_comm, self.node_request)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.ctx.destroy()

    def process_msg(self, msg):
        if msg.mtype == MsgTypes.Datagram:
            if msg.name not in self.feature_stores:
                if msg.name in self.purged:
                    logger.debug("Received data from deleted graph '%s'!", msg.name)
                else:
                    logger.warning("Received data from unknown graph '%s'!", msg.name)
            elif msg.version < self.feature_stores[msg.name].version:
                logger.warning("Received data from version %d of the graph '%s' when version %d or newer was expected!",
                               msg.version,
                               msg.name,
                               self.feature_stores[msg.name].version)
            else:
                old_names = self.feature_stores[msg.name].names
                self.feature_stores[msg.name].update(msg.payload)
                if msg.version > self.feature_stores[msg.name].version:
                    self.feature_stores[msg.name].version = msg.version
                    self.export_store(msg.name)
                elif old_names != self.feature_stores[msg.name].names:
                    # if there are new entries in the store notify the export layer
                    self.export_store(msg.name)
                # export the collector data to epics
                self.export_data(msg.name, msg.payload)
                # update the latest heartbeat indicator
                self.heartbeats[msg.name] = msg.heartbeat
                # export the heartbeat to epics
                self.export_heartbeat(msg.name)
        elif (msg.mtype == MsgTypes.Transition) and (msg.payload.ttype == Transitions.Configure):
            self.partition = msg.payload.payload
            # publish the updated partition over the info socket
            self.publish_message("sources", "manager", dill.dumps(self.partition))
            # export the partition info to epics
            self.export_config()

    @property
    def compilier_args(self):
        return {'num_workers': self.num_workers, 'num_local_collectors': self.num_nodes}

    def exists(self, name):
        return all(name in val for val in [self.feature_stores, self.graphs, self.versions])

    def create(self, name):
        if self.exists(name):
            raise ValueError("Graph with the name '%s' already exists" % name)
        else:
            self.feature_stores[name] = Store()
            self.graphs[name] = None
            self.versions[name] = 0
            self.heartbeats[name] = None
            # notify export of the new graph
            self.export_create(name)
            # remove the graph name from the purged list if there
            if name in self.purged:
                self.purged.remove(name)

    def delete(self, name):
        if self.exists(name):
            del self.feature_stores[name]
            del self.graphs[name]
            del self.versions[name]
            del self.heartbeats[name]
            # notify export of the removed graph
            self.export_destroy(name)
            # add the graph name to the purged list
            self.purged.add(name)
        else:
            raise ValueError("Graph with the name '%s' does not exist" % name)

    def names(self, name):
        name_set = set(self.partition)
        if self.graphs[name] is not None:
            name_set.update(self.graphs[name].names)
        return name_set

    def features(self, name):
        return self.feature_stores[name].types

    def feature_request(self, name, request):
        matched = self.feature_req.match(request)
        if matched:
            if matched.group('type') == 'fetch':
                if matched.group('name') in self.feature_stores[name].namespace:
                    self.comm.send_string('ok', zmq.SNDMORE)
                    self.comm.send_pyobj(self.feature_stores[name].get(matched.group('name')))
                else:
                    self.comm.send_string('error')
            else:
                self.comm.send_string('error')
            return True
        else:
            return False

    def client_request(self):
        request = self.comm.recv_string()
        if request in self.global_cmds:
            getattr(self, "cmd_%s" % request, self.cmd_unknown)()
        elif self.comm.getsockopt(zmq.RCVMORE):
            name = self.comm.recv_string()
            if not self.exists(name) and request not in self.no_auto_create_cmds:
                self.create(name)
            # check if it is a feature request
            if not self.feature_request(name, request):
                getattr(self, "cmd_%s" % request, self.cmd_unknown)(name)
        else:
            self.comm.send_string('error')

    def compile_graph(self, name):
        """
        Tries to compile the named graph. A copy of the original graph is made,
        so the original graph is uneffected by the compilation.

        Args:
            name (str): the name of the graph to compile.
        """
        graph = dill.loads(dill.dumps(self.graphs[name]))
        graph.compile(**self.compilier_args)

    def cmd_unknown(self, name=None):
        self.comm.send_string('error')

    def cmd_get_heartbeat(self, name):
        self.comm.send_pyobj(self.heartbeats[name])

    def cmd_get_versions(self, name):
        self.comm.send_pyobj((self.versions[name], self.feature_stores[name].version))

    def cmd_get_graph_version(self, name):
        self.comm.send_pyobj(self.versions[name])

    def cmd_get_features_version(self, name):
        self.comm.send_pyobj(self.feature_stores[name].version)

    def cmd_get_features(self, name):
        self.comm.send_pyobj(self.features(name))

    def cmd_get_names(self, name):
        self.comm.send_pyobj(self.names(name))

    def cmd_get_sources(self, name):
        self.comm.send_pyobj(self.partition)

    def cmd_create_graph(self, name):
        if not self.exists(name):
            self.create(name)
        self.comm.send_string('ok')

    def cmd_destroy_graph(self, name):
        if self.exists(name):
            # send a null graph to workers
            self.publish_purge(name)
            # delete the local graph information
            self.delete(name)
        else:
            self.comm.send_string('ok')

    def cmd_clear_graph(self, name):
        self.graphs[name] = None
        self.publish_graph(name)

    def cmd_reset_features(self, name):
        self.feature_stores[name].clear()
        self.feature_stores[name].version = 0
        self.export_store(name)
        self.comm.send_string('ok')

    def cmd_list_graphs(self):
        self.comm.send_pyobj(set(self.graphs))

    def cmd_get_graph(self, name):
        self.comm.send(dill.dumps(self.graphs[name]))

    def cmd_add_graph(self, name):
        nodes = dill.loads(self.comm.recv())
        backup = dill.dumps(self.graphs[name])
        try:
            if self.graphs[name] is None:
                self.graphs[name] = Graph(name)
            self.graphs[name].add(nodes)
            self.compile_graph(name)
            self.publish_delta(name, "add", nodes)
        except (AssertionError, TypeError):
            if isinstance(nodes, list):
                logger.exception("Failure encountered adding nodes \"%s\" to the graph:",
                                 ", ".join(n.name for n in nodes))
            else:
                logger.exception("Failure encountered adding node \"%s\" to the graph:", nodes.name)
            self.graphs[name] = dill.loads(backup)
            logger.info("Restored previous version of the graph (%s v%d)", name, self.versions[name])
            self.comm.send_string('error')

    def cmd_del_graph(self, name):
        nodes = dill.loads(self.comm.recv())
        if self.graphs[name] is not None:
            backup = dill.dumps(self.graphs[name])
            try:
                for node in nodes:
                    self.graphs[name].remove(node)
                # Check if the resulting graph is non-empty
                if self.graphs[name]:
                    self.compile_graph(name)
                else:
                    # if the graph is empty remove it
                    self.graphs[name] = None
                self.publish_delta(name, "del", nodes)
            except (AssertionError, TypeError):
                logger.exception("Failure encountered removing nodes \"%s\" from the graph:", nodes)
                self.graphs[name] = dill.loads(backup)
                logger.info("Restored previous version of the graph (%s v%d)", name, self.versions[name])
                self.comm.send_string('error')
        else:
            # Removing nodes that don't exist returns 'ok', so this case should too...
            self.comm.send_string('ok')

    def cmd_set_graph(self, name):
        backup = dill.dumps(self.graphs[name])
        try:
            self.graphs[name] = dill.loads(self.comm.recv())
            # Check if the graph can be compiled
            if self.graphs[name]:
                self.compile_graph(name)
            self.publish_graph(name)
        except (AssertionError, TypeError):
            logger.exception("Failure encountered compiling the requested graph:")
            self.graphs[name] = dill.loads(backup)
            logger.info("Restored previous version of the graph (%s v%d)", name, self.versions[name])
            self.comm.send_string('error')

    def publish_info(self, name):
        return name, self.versions[name], self.compilier_args

    def publish_purge(self, name):
        logger.info("Purging requested graph...")
        try:
            self.graphs[name] = None
            self.versions[name] += 1
            self.graph_comm.send_string("purge", zmq.SNDMORE)
            self.graph_comm.send_pyobj(self.publish_info(name), zmq.SNDMORE)
            self.graph_comm.send(dill.dumps(self.graphs[name]))
            self.export_graph(name)
            logger.info("Purging of graph (%s v%d) completed", name, self.versions[name])
            self.comm.send_string('ok')
        except Exception:
            logger.exception("Failed to purge graph (%s v%d) -", name, self.versions[name])
            self.comm.send_string('error')

    def publish_delta(self, name, cmd, delta):
        logger.info("Sending requested delta of graph...")
        try:
            self.versions[name] += 1
            self.graph_comm.send_string(cmd, zmq.SNDMORE)
            self.graph_comm.send_pyobj(self.publish_info(name), zmq.SNDMORE)
            self.graph_comm.send(dill.dumps(delta))
            self.export_graph(name)
            logger.info("Sending delta of graph (%s v%d) completed", name, self.versions[name])
            self.comm.send_string('ok')
        except Exception:
            logger.exception("Failed to send delta of graph (%s v%d) -", name, self.versions[name])
            self.comm.send_string('error')

    def publish_graph(self, name):
        logger.info("Sending requested graph...")
        try:
            self.versions[name] += 1
            self.graph_comm.send_string("graph", zmq.SNDMORE)
            self.graph_comm.send_pyobj(self.publish_info(name), zmq.SNDMORE)
            self.graph_comm.send(dill.dumps(self.graphs[name]))
            self.export_graph(name)
            logger.info("Sending of graph (%s v%d) completed", name, self.versions[name])
            self.comm.send_string('ok')
        except Exception:
            logger.exception("Failed to send graph (%s v%d) -", name, self.versions[name])
            self.comm.send_string('error')

    def publish_message(self, topic, node, payload):
        self.info_comm.send_string(topic, zmq.SNDMORE)
        self.info_comm.send_string(node, zmq.SNDMORE)
        self.info_comm.send(payload)

    def graph_request(self):
        request = self.graph_comm.recv_string()

        if request == "\x01":
            for name, graph in self.graphs.items():
                self.graph_comm.send_string("init", zmq.SNDMORE)
                self.graph_comm.send_pyobj(self.publish_info(name), zmq.SNDMORE)
                self.graph_comm.send(dill.dumps(graph))
            # re-ask for config information on connect
            self.graph_comm.send_string("cmd", zmq.SNDMORE)
            self.graph_comm.send_string("config")

    def node_request(self):
        topic = self.node_msg_comm.recv_string()
        node = self.node_msg_comm.recv_string()
        payload = self.node_msg_comm.recv()

        self.publish_message(topic, node, payload)

    def export_graph(self, name):
        if self.export is not None:
            data = {
                'names': self.names(name),
                'sources': self.partition,
                'version': self.versions[name],
                'dill': dill.dumps(self.graphs[name])
            }
            self.export.send_string('graph', zmq.SNDMORE)
            self.export.send_string(name, zmq.SNDMORE)
            self.export.send_pyobj(data)

    def export_store(self, name):
        if self.export is not None:
            data = {
                'version': self.feature_stores[name].version,
                'features': self.features(name),
            }
            self.export.send_string('store', zmq.SNDMORE)
            self.export.send_string(name, zmq.SNDMORE)
            self.export.send_pyobj(data)

    def export_info(self):
        if self.export is not None:
            data = {
                'graphs': set(self.graphs),
            }
            self.export.send_string('info', zmq.SNDMORE)
            self.export.send_string("", zmq.SNDMORE)
            self.export.send_pyobj(data)

    def export_config(self):
        self.export_info()
        for name in self.feature_stores:
            self.export_store(name)
        for name in self.graphs:
            self.export_graph(name)

    def export_create(self, name):
        self.export_info()
        self.export_store(name)
        self.export_graph(name)

    def export_destroy(self, name):
        self.export_info()
        if self.export is not None:
            self.export.send_string('destroy', zmq.SNDMORE)
            self.export.send_string(name, zmq.SNDMORE)
            self.export.send_pyobj(None)

    def export_data(self, name, data):
        if self.export is not None:
            self.export.send_string('data', zmq.SNDMORE)
            self.export.send_string(name, zmq.SNDMORE)
            self.export.send_pyobj(data)

    def export_heartbeat(self, name):
        if self.export is not None:
            self.export.send_string('heartbeat', zmq.SNDMORE)
            self.export.send_string(name, zmq.SNDMORE)
            self.export.send_pyobj(self.heartbeats[name])


def run_manager(num_workers, num_nodes, results_addr, graph_addr, comm_addr, msg_addr, info_addr, export_addr=None):
    logger.info('Starting manager, controlling %d workers on %d nodes', num_workers, num_nodes)
    with Manager(
            num_workers,
            num_nodes,
            results_addr,
            graph_addr,
            comm_addr,
            msg_addr,
            info_addr,
            export_addr) as manager:
        return manager.run()


def main():
    parser = argparse.ArgumentParser(description='AMII Manager App')

    parser.add_argument(
        '-H',
        '--host',
        default='*',
        help='interface the AMII manager listens on (default: all)'
    )

    parser.add_argument(
        '-p',
        '--port',
        type=int,
        default=Ports.Comm,
        help='port for GUI-Manager communication (default: %d)' % Ports.Comm
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
        '--num-nodes',
        type=int,
        default=1,
        help='number of nodes (a.k.a local collector processes) (default: 1)'
    )

    parser.add_argument(
        '-g',
        '--graph',
        type=int,
        default=Ports.Graph,
        help='port for graph communication (default: %d)' % Ports.Graph
    )

    parser.add_argument(
        '-e',
        '--export',
        type=int,
        default=Ports.Export,
        help='port for sending data to the export service (default: %d)' % Ports.Export
    )

    parser.add_argument(
        '-r',
        '--results',
        type=int,
        default=Ports.Results,
        help='port for receiving results (default: %d)' % Ports.Results
    )

    parser.add_argument(
        '-m',
        '--message',
        type=int,
        default=Ports.Message,
        help='port for receiving out-of-band messages from nodes (default: %d)' % Ports.Message
    )

    parser.add_argument(
        '-I',
        '--info',
        type=int,
        default=Ports.Info,
        help='port for status information communication (default: %d)' % Ports.Info
    )

    parser.add_argument(
        '-E',
        '--enable-export',
        action='store_true',
        help='enable the data export service'
    )

    parser.add_argument(
        '--log-level',
        default=LogConfig.Level,
        help='the logging level of the application (default %s)' % LogConfig.Level
    )

    parser.add_argument(
        '--log-file',
        help='an optional file to write the log output to'
    )

    args = parser.parse_args()

    results_addr = "tcp://%s:%d" % (args.host, args.results)
    graph_addr = "tcp://%s:%d" % (args.host, args.graph)
    comm_addr = "tcp://%s:%d" % (args.host, args.port)
    msg_addr = "tcp://%s:%d" % (args.host, args.message)
    info_addr = "tcp://%s:%d" % (args.host, args.info)
    if args.enable_export:
        export_addr = "tcp://%s:%d" % (args.host, args.export)
    else:
        export_addr = None

    log_handlers = [logging.StreamHandler()]
    if args.log_file is not None:
        log_handlers.append(logging.FileHandler(args.log_file))
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(format=LogConfig.Format, level=log_level, handlers=log_handlers)

    try:
        return run_manager(args.num_workers,
                           args.num_nodes,
                           results_addr,
                           graph_addr,
                           comm_addr,
                           msg_addr,
                           info_addr,
                           export_addr)
    except KeyboardInterrupt:
        logger.info("Manager killed by user...")
        return 0


if __name__ == '__main__':
    sys.exit(main())
