import importlib
import collections


class GraphConfigError(Exception):
    pass


class GraphRuntimeError(Exception):
    pass


class Graph(object):
    def __init__(self, store, cfg=None):
        self.cfg_old = {}
        self.sources = []
        if cfg is None:
            self.cfg = {}
        else:
            self.cfg = cfg
        self.subs = {}
        self.store = store
        self.operations = []

    @staticmethod
    def build_node(code, inputs, outputs, config=None, imports=None, setup=None):
        # code to be executed on each event
        cfg = {"code": code}
        # make inputs into list if not
        if not isinstance(inputs, str) and isinstance(inputs, collections.Sequence):
            cfg["inputs"] = inputs
        else:
            cfg["inputs"] = [inputs]
        # make outputs into list if not
        if not isinstance(outputs, str) and isinstance(outputs, collections.Sequence):
            cfg["outputs"] = outputs
        else:
            cfg["outputs"] = [outputs]
        # add config if passed in - these are constants to be used executed code
        if config is not None:
            cfg["config"] = config
        # add imports if passed in
        if imports is not None:
            cfg["imports"] = imports
        # add setup code to be executed on setup
        if setup is not None:
            cfg["setup"] = setup
        return cfg

    @staticmethod
    def generate_tree(cfg):
        """
        Generate a dependency tree from a config input

        Parameters
        ----------
        cfg : json config object

        Returns
        -------
        graph : dict
            dict where the keys are operations, the value are upstream
            (dependent) operations that should be done first
        """
        graph = {}
        for op in cfg:
            graph[op] = cfg[op]['inputs']
        return graph

    @staticmethod
    def resolve_dependencies(dependencies):
        """
        Dependency resolver

        Parameters
        ----------
        dependencies : dict
            the values are the dependencies of their respective keys

        Returns
        -------
        order : list
            a list of the order in which to resolve dependencies
        """

        # this just makes sure there are no duplicate dependencies
        d = dict((k, set(dependencies[k])) for k in dependencies)

        # output list
        r = []

        while d:

            # find all nodes without dependencies (roots)
            t = set(i for v in d.values() for i in v) - set(d.keys())

            # and items with no dependencies (disjoint nodes)
            t.update(k for k, v in d.items() if not v)

            # both of these can be resolved
            r.extend(t)

            # remove resolved depedencies from the tree
            d = dict(((k, v-t) for k, v in d.items() if v))

        return r

    @staticmethod
    def extract_collection_strategies(graph):
        strategies = {}
        for op in graph.values():
            for name, strat in op['outputs']:
                strategies[name] = strat
        return strategies

    def configure(self, sources):
        self.operations = []
        # loop over operations in the correct order
        # should we throw an error if there are dups in the cfg?
        for op in Graph.resolve_dependencies(Graph.generate_tree(self.cfg)):
            # this takes care of "base" data (e.g. given by the DAQ)
            if op in sources:
                continue

            try:
                # at the end of the executed code, inject outputs in to the feature store
                auto_put = True
                if 'auto_put' in self.cfg[op]:
                    auto_put = self.cfg[op]['auto_put']
                if auto_put:
                    store_put_list = ['store.put("%s", %s)' % (output, output) for output, _ in self.cfg[op]['outputs']]
                    store_put = '\n' + '; '.join(store_put_list)

                # generate the global namespace for the execution of the graph operation
                glb = {}  # {"np" : np} # TODO be smarter :)
                loc = {}
                if 'imports' in self.cfg[op]:
                    for import_info in self.cfg[op]['imports']:
                        try:
                            imp, imp_name = import_info
                        except ValueError:
                            imp = import_info
                            imp_name = imp
                        glb[imp_name] = importlib.import_module(imp)
                if 'config' in self.cfg[op]:
                    glb['config'] = self.cfg[op]['config']
                if 'setup' in self.cfg[op]:
                    exec(self.cfg[op]['setup'], glb, loc)

                self.operations.append((op, compile(self.cfg[op]['code'] + store_put, '<string>', 'exec'), glb, loc))
            except Exception as exp:
                raise GraphConfigError("exception encounterd adding operation %s to the graph: %s" % (op, exp))
        self.sources = sources

    def revert(self):
        self.cfg = self.cfg_old
        self.configure(self.sources)

    def execute(self):
        for op, code, glb, loc in self.operations:
            # check if all inputs have new data
            ready = True
            for inp in self.cfg[op]['inputs']:
                if not self.store.is_ready(inp):  # and required? do we still want that
                    ready = False
            try:
                if ready:
                    # fetch the current result store namespace
                    loc['store'] = self.store
                    loc.update(self.store.namespace)
                    # exec compiled code
                    exec(code, glb, loc)
            except Exception as exp:
                raise GraphRuntimeError("exception encounterd running operation %s on the graph: %s" % (op, exp))

    def update(self, new_cfg):
        self.cfg_old = self.cfg
        self.cfg = new_cfg
