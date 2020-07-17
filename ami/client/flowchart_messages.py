class Msg(object):

    def __init__(self, name):
        self.name = name


class BrokerMsg(Msg):

    """
    Messages to command the broker to do something.
    """

    def __init__(self, name):
        super().__init__(name)


class NodeMsg(Msg):

    """
    Messages which should be cached and forwarded to node processes.
    """

    def __init__(self, name):
        super().__init__(name)


class CreateNode(BrokerMsg):

    def __init__(self, name, node_type, state={}):
        super().__init__(name)
        self.node_type = node_type
        self.state = state

    def __repr__(self):
        return f"CreateNode(name={self.name}, node_type={self.node_type}, state={self.state})"


class CloseNode(NodeMsg):

    def __init__(self):
        super().__init__("")


class DisplayNode(NodeMsg):

    def __init__(self, name, topics, terms, state={}, units={}, redisplay=False):
        super().__init__(name)
        self.topics = topics
        self.terms = terms
        self.state = state
        self.units = units
        self.redisplay = redisplay

    def __repr__(self):
        return f"""DisplayNode(name={self.name},
        topics={self.topics},
        terms={self.terms},
        units={self.units},
        redisplay={self.redisplay})"""


class NodeCheckpoint(NodeMsg):

    def __init__(self, name, state={}):
        super().__init__(name)
        self.state = state


class Profiler(Msg):

    def __init__(self, name, command):
        super().__init__(name)
        self.command = ""
