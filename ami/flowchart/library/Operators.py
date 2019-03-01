from ami.flowchart.Node import Node
import ami.graph_nodes as gn
import numpy as np


class Sum(Node):

    nodeName = "Sum"

    def __init__(self, name):
        super(Sum, self).__init__(name, terminals={
            'In': {'io': 'in', 'type': (np.ndarray, list)},
            'Out': {'io': 'out', 'type': np.float64}
        })

    def to_operation(self, inputs, conditions=[]):
        outputs = self.output_vars()
        node = gn.Map(name=self.name()+"_operation",
                      condition_needs=conditions, inputs=inputs, outputs=outputs,
                      func=np.sum)
        return node


class Binning(Node):

    nodeName = "Binning"

    def __init__(self, name):
        super(Binning, self).__init__(name, terminals={
            'Values': {'io': 'in', 'type': np.float64},
            'Bins': {'io': 'in', 'type': int},
            'Out': {'io': 'out', 'type': dict}
        })

    def connected(self, localTerm, remoteTerm):
        if localTerm.name() == "Bins":
            super(Binning, self).connected(localTerm, remoteTerm, pos=0)
        elif localTerm.name() == "Values":
            super(Binning, self).connected(localTerm, remoteTerm, pos=1)
        else:
            super(Binning, self).connected(localTerm, remoteTerm)

    def to_operation(self, inputs, conditions=[]):
        outputs = self.output_vars()
        node = gn.Binning(name=self.name()+"_operation", condition_needs=conditions, inputs=inputs, outputs=outputs)
        return node
