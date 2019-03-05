class Msg(object):

    def __init__(self, name):
        self.name = name


class BrokerMsg(Msg):

    """
    Messages to command the broker to do something.
    """

    def __init__(self, name):
        super(BrokerMsg, self).__init__(name)


class NodeMsg(Msg):

    """
    Messages which should be cached and forwarded to node processes.
    """

    def __init__(self, name):
        super(NodeMsg, self).__init__(name)


class CreateNode(BrokerMsg):

    def __init__(self, name, node_type):
        super(CreateNode, self).__init__(name)
        self.node_type = node_type


class CloseNode(NodeMsg):

    def __init__(self):
        super(CloseNode, self).__init__("")


class DisplayNode(NodeMsg):

    def __init__(self, name, topics):
        super(DisplayNode, self).__init__(name)
        self.topics = topics


class UpdateNodeAttributes(NodeMsg):

    def __init__(self, node_name, inputs=None, conditions=None):
        super(UpdateNodeAttributes, self).__init__(node_name)
        self.inputs = inputs
        self.conditions = conditions


class NodeCheckpoint(NodeMsg):

    def __init__(self, node_name, inputs=None, conditions=None, state=None):
        super(NodeCheckpoint, self).__init__(node_name)
        self.inputs = inputs
        self.conditions = conditions
        self.state = state


class GetNodeOperation(NodeMsg):

    def __init__(self):
        super(GetNodeOperation, self).__init__("")