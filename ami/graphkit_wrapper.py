import networkx as nx
import itertools as it
import collections
from networkfox import compose, Var
import ami.graph_nodes


class Graph():

    def __init__(self, name):
        """
        Args:
            name (str): Name of graph
        """

        self.name = name
        self.graph = nx.DiGraph()
        self.graphkit = None
        self.global_operations = set()
        self.expanded_global_operations = set()
        self.children_of_global_operations = {}
        self.inputs = collections.defaultdict(set)
        self.outputs = collections.defaultdict(set)

    def __bool__(self):
        return self.graph.size() != 0

    def _name_is_valid(self, name):
        """
        Returns true if the name passed is a valid user-defined name for inputs
        and outputs in the graph.

        In other words this checks if the name collides with one the graph may
        generate internally.

        Args:
            name (str): the name whose validity will be checked

        Returns:
            True if the name is valid, False otherwise.
        """
        if isinstance(name, str):
            return not name.endswith(('_worker', '_localCollector', '_globalCollector'))
        else:
            return False

    @property
    def variables(self):
        """
        Returns a set of all nodes of type `Var` in the graph.

        Returns:
            A set of all `Var` nodes.
        """
        return {node for node in self.graph.nodes if isinstance(node, Var)}

    @property
    def names(self):
        """
        Returns a set of all user-defined names in the graph that can be used
        as inputs for nodes. Internally generated names are exclued from this
        list!

        Returns:
            The set of user-defined names
        """
        return {node.name for node in self.variables if self._name_is_valid(node.name)}

    @property
    def sources(self):
        """
        Returns a set of all input data sources needed by the worker to process
        the full graph.

        Returns:
            The set of all the input data sources
        """
        sources = set()

        for var in self.inputs['worker']:
            if isinstance(var, Var):
                var = var.name
            if self._name_is_valid(var):
                sources.add(var)

        return sources

    def get_type(self, name):
        """
        Returns the type of a Var node in the graph

        Args:
            name (str): The name field of the Var node in graph

        Returns:
            The type of the Var node if found
        """
        for node in self.graph.nodes:
            if isinstance(node, Var) and node.name == name:
                return node.type

    def add(self, op):
        """
        Add an operation to the graph. If the node already exists in the graph try to replace it if the new node's
        inputs and outputs match the old one's.

        Args:
            op (list or Transformation): Operation node to add to graph.
        """

        try:
            self.insert(op)
        except AssertionError:
            self.replace(op)

    def insert(self, ops):
        """
        Insert operations into the graph. If an operation already exists in the graph this function raises an
        AssertionError.

        Args:
            ops (list or Transformation): Operation to insert into graph

        Raises:
            AssertionError: if an operation already exists in the graph
        """

        if type(ops) is not list:
            ops = [ops]

        for op in ops:
            assert op not in self.graph.nodes(), "Operation may only be added once %s" % op.name
            assert op.name not in self.children_of_global_operations, "Operation may only be added once %s" % op.name

            for i in op.inputs:
                self.graph.add_edge(i, op)

            for o in op.outputs:
                self.graph.add_edge(op, o)

            for i in op.condition_needs:
                self.graph.add_edge(i, op)

        self.graphkit = None

    def remove(self, name):
        """
        Recursively removes a node and its descendants from the graph.

        Args:
            name (str): Name of node to remove from graph.
        """

        for n in self.graph.nodes:
            if type(n) is str:
                continue
            if n.name == name:
                desc = nx.dag.descendants(self.graph, n)
                self.graph.remove_nodes_from(desc)
                self.graph.remove_node(n)
                break
        if name in self.children_of_global_operations:
            for child in self.children_of_global_operations[name]:
                self.remove(child.name)
                if child in self.expanded_global_operations:
                    self.expanded_global_operations.remove(child)
            del self.children_of_global_operations[name]

        self.graphkit = None

    def replace(self, new_node):
        """
        Replace a node in the graph. Inputs and outputs of new_node must match the existing node in the graph otherwise
        an AssertionError will be raised.

        Args:
            new_node (Transformation): New node to replace existing node with.

        Raises:
            AssertionError: if inputs and outputs of new_node do not match existing node.
        """

        if new_node.name in self.children_of_global_operations:
            descendants = set()
            ancestors = set()
            for child in self.children_of_global_operations[new_node.name]:
                if child.name == '%s_worker' % new_node.name:
                    descendants.add(child)
                    descendants.update(nx.dag.descendants(self.graph, child))
                    assert set(child.inputs) == set(new_node.inputs), "Inputs must match."
                if child.name == '%s_globalCollector' % new_node.name:
                    ancestors.add(child)
                    ancestors.update(nx.dag.ancestors(self.graph, child))
                    assert set(child.outputs) == set(new_node.outputs), "Outputs must match."
            nodes_to_remove = descendants.intersection(ancestors)

            self.graph.remove_nodes_from(nodes_to_remove)
            for node in nodes_to_remove:
                if node in self.expanded_global_operations:
                    self.expanded_global_operations.remove(node)
            del self.children_of_global_operations[new_node.name]
        else:
            old_node = None
            for n in self.graph.nodes:
                if type(n) is str:
                    continue
                if n.name == new_node.name:
                    old_node = n
                    break

            assert old_node is not None, "Old node not found: %s" % new_node.name
            assert set(old_node.inputs) == set(new_node.inputs), "Inputs must match."
            assert set(old_node.outputs) == set(new_node.outputs), "Outputs must match."

            self.graph.remove_node(old_node)

        self.insert(new_node)

        self.graphkit = None

    def reset(self):
        """
        Resets the state of all StatefulTransmation nodes in the graph.
        """
        nodes = list(filter(lambda node: isinstance(node, ami.graph_nodes.StatefulTransformation), self.graph.nodes))
        list(map(lambda node: node.reset(), nodes))

    def _color_nodes(self):
        """
        Generate all paths from inputs to outputs, for each path look for nodes which have the ``is_global_operation``
        attribute set to True. If in a given path for which we've found a global operation node there is no
        other node with ``is_global_operation`` true which preceeds it then we mark that node for expansion.
        """
        inputs = [n for n, d in self.graph.in_degree() if d == 0]
        outputs = [n for n, d in self.graph.out_degree() if d == 0]

        self.global_operations = set()
        sources_targets = list(it.product(inputs, outputs))
        for s, t in sources_targets:
            paths = list(nx.algorithms.all_simple_paths(self.graph, s, t))
            for nodes in paths:
                reductions = list(filter(lambda node: getattr(node, 'is_global_operation', False), nodes))

                for reduction in reductions:
                    if reduction in self.expanded_global_operations:
                        continue
                    before = list(filter(lambda node: getattr(node, 'is_global_operation', False),
                                         nx.algorithms.dag.ancestors(self.graph, reduction)))
                    if before == []:
                        self.global_operations.add(reduction)

                color = 'worker'
                for node in nodes:
                    if type(node) is str or isinstance(node, Var):
                        continue

                    if node in self.global_operations or node in self.expanded_global_operations:
                        color = 'globalCollector'
                    if node.color == "":
                        node.color = color

    def _expand_global_operations(self, num_workers, num_local_collectors):
        """
        Expand the nodes found in color_nodes into three nodes which execute on the worker, local collector, and
        global collector respectively. The number of workers and number of local collectors must be known in order to
        properly expand PickN operations.

        Args:
            num_workers (int): Total number of workers.
            num_local_collectors (int): Total number of local collectors.
        """

        inputs = [n for n, d in self.graph.in_degree() if d == 0]
        self.inputs['worker'].update(inputs)

        for node in self.global_operations:
            inputs = node.inputs
            outputs = node.outputs
            condition_needs = node.condition_needs
            self.children_of_global_operations[node.name] = set()

            self.graph.remove_node(node)
            NewNode = getattr(ami.graph_nodes, node.__class__.__name__)

            color_order = ['worker', 'localCollector', 'globalCollector']
            worker_outputs = None
            local_collector_outputs = None
            for color in color_order:

                if color == 'worker':
                    worker_outputs = list(map(lambda o: Var(name=o.name+'_worker', type=o.type), node.outputs))

                    worker_N = 1
                    if hasattr(node, 'N'):
                        worker_N = max(node.N // num_workers, 1)

                    worker_node = NewNode(name=node.name+'_worker', inputs=inputs, outputs=worker_outputs,
                                          condition_needs=condition_needs, reduction=node.reduction, N=worker_N)
                    worker_node.color = color
                    worker_node.is_global_operation = False
                    self.children_of_global_operations[node.name].add(worker_node)
                    self.outputs[color].update(worker_outputs)
                    for i in inputs:
                        self.graph.add_edge(i, worker_node)
                    for o in worker_outputs:
                        self.graph.add_edge(worker_node, o)
                    for n in condition_needs:
                        self.graph.add_edge(n, worker_node)

                elif color == 'localCollector':
                    self.inputs[color].update(worker_outputs)
                    local_collector_outputs = list(map(lambda o: Var(name=o.name+'_localCollector', type=o.type),
                                                       node.outputs))

                    local_collector_N = 1
                    if hasattr(node, 'N'):
                        local_collector_N = max(node.N // num_local_collectors, 1)

                    local_collector_node = NewNode(name=node.name+'_localCollector', inputs=worker_outputs,
                                                   outputs=local_collector_outputs, reduction=node.reduction,
                                                   N=local_collector_N)
                    local_collector_node.color = color
                    local_collector_node.is_global_operation = False
                    self.children_of_global_operations[node.name].add(local_collector_node)
                    self.outputs[color].update(local_collector_outputs)
                    for i in worker_outputs:
                        self.graph.add_edge(i, local_collector_node)
                    for o in local_collector_outputs:
                        self.graph.add_edge(local_collector_node, o)

                elif color == 'globalCollector':
                    self.inputs[color].update(local_collector_outputs)

                    N = getattr(node, 'N', 1)
                    N = max((N // num_workers)*num_workers, 1)

                    global_collector_node = NewNode(name=node.name+'_globalCollector',
                                                    inputs=local_collector_outputs,
                                                    outputs=outputs, reduction=node.reduction, N=N)
                    global_collector_node.color = color
                    self.children_of_global_operations[node.name].add(global_collector_node)
                    self.expanded_global_operations.add(global_collector_node)
                    for i in local_collector_outputs:
                        self.graph.add_edge(i, global_collector_node)
                    for o in outputs:
                        self.graph.add_edge(global_collector_node, o)

    def _generate_filter_node(self, seen, filter_node, nodes):
        """
        Convert a Filter node to appropriate networkfox if/else node.

        Args:
            seen (set): Set of nodes that have already been converted.
            filter_node (Filter): Node to convert to networkfox if/else node.
            nodes (list): Nodes which will make up subgraph contained in networkfox if/else node.

        Returns:
            node: networkfox if/else node.
        """
        seen.update(nodes)
        nodes.pop(0)
        nodes.pop(0)
        subgraph = self.graph.subgraph(nodes)
        inputs = [n for n, d in subgraph.in_degree() if d == 0]
        inputs = list(it.chain.from_iterable([i.inputs for i in inputs]))
        outputs = [n for n, d in subgraph.out_degree() if d == 0]
        nodes = list(filter(lambda node: not isinstance(node, Var), nodes))
        nodes = list(map(lambda node: node.to_operation(), nodes))
        node = filter_node.to_operation()
        if hasattr(filter_node, 'condition'):
            node = node(name=filter_node.name,
                        condition_needs=filter_node.condition_needs, condition=filter_node.condition,
                        needs=inputs, provides=outputs)(*nodes)
        else:
            node = node(name=filter_node.name,
                        condition_needs=filter_node.condition_needs,
                        needs=inputs, provides=outputs)(*nodes)

        return node

    def _collect_global_inputs(self):
        """
        Insert Pick1 for nodes which run global collector but depend on inputs which are only available on worker.
        """
        inputs = [n for n, d in self.graph.in_degree() if d == 0]

        global_collector_nodes = list(filter(lambda node: getattr(node, 'color', '') == 'globalCollector',
                                             self.graph.nodes))
        for node in global_collector_nodes:
            new_inputs = []
            update_inputs = False
            if node in self.global_operations:
                continue
            for i in node.inputs:
                if i in inputs:
                    pickone = ami.graph_nodes.PickN(name=i.name+"_pick1",
                                                    inputs=[i],
                                                    outputs=[Var(name="one_"+i.name, type=i.type)])
                    self.global_operations.add(pickone)
                    self.add(pickone)
                    update_inputs = True
                    new_inputs.extend(pickone.outputs)
                else:
                    new_inputs.append(i)
            self.graph.remove_node(node)
            if update_inputs:
                node.inputs = new_inputs
            self.add(node)

    def compile(self, num_workers=1, num_local_collectors=1):
        """
        Convert an AMI graph to a networkfox graph. This function must be called after any function which modifies the
        graph, ie add, insert, remove, or replace.

        This is done by coloring nodes, expanding global operations, and replacing filter nodes with the appropriate
        networkfox equivalents.

        Args:
            num_workers (int): Total number of workers.
            num_local_collectors (int): Total number of local collectors.
        """
        self.inputs = collections.defaultdict(set)
        self._color_nodes()
        self._collect_global_inputs()
        self._expand_global_operations(num_workers, num_local_collectors)

        seen = set()
        branch_merge_candidates = [n for n, d in self.graph.in_degree() if d >= 2 and isinstance(n, Var)]
        graph_filters = list(filter(lambda node: isinstance(node, ami.graph_nodes.Filter), self.graph.nodes))
        outputs = [n for n, d in self.graph.out_degree() if d == 0]
        body = []

        # There are two cases that need to be handled when converting filter nodes.
        # Filters which merge two branches of the graph and filters which don't merge branches.

        filters_targets = list(it.product(graph_filters, branch_merge_candidates))
        for f, t in filters_targets:
            paths = list(nx.algorithms.all_simple_paths(self.graph, f, t))

            for nodes in paths:
                filter_node = self._generate_filter_node(seen, f, nodes)
                body.append(filter_node)

        filters_targets = list(it.product(graph_filters, outputs))
        for f, t in filters_targets:
            paths = list(nx.algorithms.all_simple_paths(self.graph, f, t))

            for nodes in paths:
                if any(map(lambda node: node in branch_merge_candidates, nodes)):
                    continue
                if seen.issuperset(nodes):
                    continue

                filter_node = self._generate_filter_node(seen, f, nodes)
                body.append(filter_node)

        for node in self.graph.nodes:
            if node in seen:
                continue
            if type(node) is str or isinstance(node, Var):
                continue
            body.append(node.to_operation())

        self.outputs['globalCollector'].update(outputs)

        self.graphkit = compose(name=self.name)(*body)

    def nxplot(self, filename=None):
        A = nx.nx_agraph.to_agraph(self.graph)
        A.layout(prog='dot')
        A.draw(filename)

    def plot(self, filename=None):
        """
        Generate plot of the graph.

        See networkfox documentation for options.

        Args:
            filename (str): Name of file to save plot to.

        Raises:
            AssertionError: if compile() has not been called first
        """
        assert self.graphkit is not None, "call compile first"

        self.graphkit.plot(filename)

    def __call__(self, *args, **kwargs):
        """
        Executes the graph. The dictionary returned by this function will only contain entries for
        the keys in self.outputs for the given color.

        :param args: args[0] should be dictionary of arguments required to execute graph nodes.
        :param kwargs: Should contain a key called color with a valid color, either worker, localCollector,
                       or globalCollector.
        :raises AssertionError: if compile() has not been falled first or if color is None.
        """
        assert self.graphkit is not None, "call compile first"

        color = kwargs.get('color', None)
        assert color is not None
        result = self.graphkit(*args, **kwargs)
        outputs = self.outputs[color]
        return {k.name: result[k.name] for k in outputs if k.name in result}
