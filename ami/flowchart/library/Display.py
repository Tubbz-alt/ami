from typing import Dict
from ami.flowchart.library.DisplayWidgets import ScalarWidget, ScatterWidget, WaveformWidget, AreaDetWidget, LineWidget
from ami.flowchart.library.DisplayWidgets import HistogramWidget
from ami.flowchart.library.common import CtrlNode, MAX
from amitypes import Array1d, Array2d, HSDWaveforms
import ami.graph_nodes as gn


class ScalarViewer(CtrlNode):

    """
    ScalarViewer displays the value of a scalar.
    """

    nodeName = "ScalarViewer"
    uiTemplate = []

    def __init__(self, name):
        super(ScalarViewer, self).__init__(name,
                                           terminals={"In": {"io": "in", "ttype": float}},
                                           viewable=True)

    def display(self, topics, addr, win, **kwargs):
        return super(ScalarViewer, self).display(topics, addr, win, ScalarWidget, **kwargs)


class WaveformViewer(CtrlNode):

    """
    WaveformViewer displays 1D arrays.
    """

    nodeName = "WaveformViewer"
    uiTemplate = []

    def __init__(self, name):
        super(WaveformViewer, self).__init__(name, terminals={"In": {"io": "in", "ttype": Array1d}},
                                             viewable=True)

    def display(self, topics, addr, win, **kwargs):
        return super(WaveformViewer, self).display(topics, addr, win, WaveformWidget, **kwargs)


class ImageViewer(CtrlNode):

    """
    ImageViewer displays 2D arrays.
    """

    nodeName = "ImageViewer"
    uiTemplate = []

    def __init__(self, name):
        super(ImageViewer, self).__init__(name, terminals={"In": {"io": "in", "ttype": Array2d}}, viewable=True)

    def display(self, topics, addr, win, **kwargs):
        return super(ImageViewer, self).display(topics, addr, win, AreaDetWidget, **kwargs)


class Histogram(CtrlNode):

    """
    Histogram plots a histogram created from either Binning or BinByVar.
    """

    nodeName = "Histogram"
    uiTemplate = []

    def __init__(self, name):
        super(Histogram, self).__init__(name,
                                        terminals={"In": {"io": "in", "ttype": Dict[float, float]}},
                                        allowAddInput=True,
                                        viewable=True)

    def display(self, topics, addr, win, **kwargs):
        return super(Histogram, self).display(topics, addr, win, HistogramWidget, **kwargs)


class ScatterPlot(CtrlNode):

    """
    Scatter Plot collects two scalars and plots them against each other.
    """

    nodeName = "ScatterPlot"
    uiTemplate = [("Num Points", 'intSpin', {'value': 100, 'min': 1, 'max': MAX})]

    def __init__(self, name):
        super(ScatterPlot, self).__init__(name, terminals={"X": {"io": "in", "ttype": float},
                                                           "Y": {"io": "in", "ttype": float}},
                                          allowAddInput=True,
                                          buffered=True)

    def display(self, topics, addr, win, **kwargs):
        return super(ScatterPlot, self).display(topics, addr, win, ScatterWidget, **kwargs)

    def addInput(self, **args):
        self.addTerminal(name="X", io='in', ttype=float, **args)
        self.addTerminal(name="Y", io='in', ttype=float, **args)

    def to_operation(self, inputs, conditions={}):
        outputs = [self.name()]
        node = gn.RollingBuffer(name=self.name()+"_operation", N=self.Num_Points,
                                conditions_needs=list(conditions.values()), inputs=list(inputs.values()),
                                outputs=outputs)
        return node


class ScalarPlot(CtrlNode):

    """
    Scalar Plot collects scalars and plots them.
    """

    nodeName = "ScalarPlot"
    uiTemplate = [("Num Points", 'intSpin', {'value': 100, 'min': 1, 'max': MAX})]

    def __init__(self, name):
        super(ScalarPlot, self).__init__(name, terminals={"Y": {"io": "in", "ttype": float}},
                                         allowAddInput=True,
                                         buffered=True)

    def addInput(self, **args):
        self.addTerminal(name="Y", io='in', ttype=float, **args)

    def display(self, topics, addr, win, **kwargs):
        return super(ScalarPlot, self).display(topics, addr, win, WaveformWidget, **kwargs)

    def to_operation(self, inputs, conditions={}):
        outputs = [self.name()]
        node = gn.RollingBuffer(name=self.name()+"_operation", N=self.Num_Points,
                                conditions_needs=list(conditions.values()), inputs=list(inputs.values()),
                                outputs=outputs)
        return node


class LinePlot(CtrlNode):

    """
    Line Plot plots arrays.
    """

    nodeName = "LinePlot"
    uiTemplate = []

    def __init__(self, name):
        super(LinePlot, self).__init__(name, terminals={"X": {"io": "in", "ttype": Array1d},
                                                        "Y": {"io": "in", "ttype": Array1d}},
                                       allowAddInput=True,
                                       buffered=True)

    def display(self, topics, addr, win, **kwargs):
        return super(LinePlot, self).display(topics, addr, win, LineWidget, **kwargs)

    def addInput(self, **args):
        self.addTerminal(name="X", io='in', ttype=Array1d, **args)
        self.addTerminal(name="Y", io='in', ttype=Array1d, **args)


class HSDViewer(CtrlNode):

    """
    HSDViewer
    """

    nodeName = "HSDViewer"
    uiTemplate = [("Channel", 'combo', {'values': ["0", "1", "2", "3", "4"], 'index': 0})]

    def __init__(self, name):
        super(HSDViewer, self).__init__(name, terminals={"In": {"io": "in", "ttype": HSDWaveforms}},
                                        buffered=True)

    def display(self, topics, addr, win, **kwargs):
        return super(HSDViewer, self).display(topics, addr, win, LineWidget, **kwargs)

    def to_operation(self, inputs, conditions={}):
        map_outputs = [self.name()+"_map"]
        outputs = [self.name()]
        k = int(self.Channel)

        node = [gn.Map(name=self.name()+"_operation",
                       condition_needs=list(conditions.values()), inputs=list(inputs.values()), outputs=map_outputs,
                       func=lambda d: {'x': d['times'], 'y': d[k]} if k in d else {}),
                gn.PickN(name=self.name()+"_picked",
                         inputs=map_outputs, outputs=outputs)]
        return node
