from ami.flowchart.library.common import CtrlNode, MAX
from amitypes import Array1d, Array2d
import ami.graph_nodes as gn
import numpy as np


try:
    import constFracDiscrim as cfd

    class CFD(CtrlNode):

        """
        Constant fraction descriminator
        """

        nodeName = "CFD"
        uiTemplate = [('Sample Interval', 'doubleSpin', {'value': 1, 'min': 0.01, 'max': MAX}),
                      ('horpos', 'doubleSpin', {'value': 0, 'min': 0, 'max': MAX}),
                      ('gain', 'doubleSpin', {'value': 1, 'min': 0.01, 'max': MAX}),
                      ('offset', 'doubleSpin', {'value': 0, 'min': 0, 'max': MAX}),
                      ('delay', 'intSpin', {'value': 1, 'min': 0, 'max': MAX}),
                      ('walk', 'doubleSpin', {'value': 0, 'min': 0, 'max': MAX}),
                      ('threshold', 'doubleSpin', {'value': 0, 'min': 0, 'max': MAX}),
                      ('fraction', 'doubleSpin', {'value': 0.5, 'min': 0, 'max': MAX})]

        def __init__(self, name):
            super().__init__(name, terminals={'In': {'io': 'in', 'ttype': Array1d},
                                              'Out': {'io': 'out', 'ttype': float}})

        def to_operation(self, inputs, conditions={}):
            outputs = self.output_vars()

            sampleInterval = self.Sample_Interval
            horpos = self.horpos
            gain = self.gain
            offset = self.offset
            delay = self.delay
            walk = self.walk
            threshold = self.threshold
            fraction = self.fraction

            def cfd_func(waveform):
                return cfd.cfd(sampleInterval, horpos, gain, offset, waveform, delay, walk, threshold, fraction)

            node = gn.Map(name=self.name()+"_operation",
                          condition_needs=list(conditions.values()), inputs=list(inputs.values()), outputs=outputs,
                          func=cfd_func,
                          parent=self.name())
            return node

except ImportError:
    pass

try:
    import psana.hexanode.WFPeaks as psWFPeaks

    class WFPeaks(CtrlNode):

        """
        WFPeaks
        """

        nodeName = "WFPeaks"
        uiTemplate = [('num chans', 'combo', {'values': ["5", "7", "16"]}),
                      ('num hits', 'intSpin', {'value': 16, 'min': 1, 'max': MAX}),
                      ('base', 'doubleSpin', {'value': 0., 'min': 0., 'max': MAX}),
                      ('thr', 'doubleSpin', {'value': -0.05, 'min': -MAX, 'max': MAX}),
                      ('cfr', 'doubleSpin', {'value': 0.85, 'max': MAX}),
                      ('deadtime', 'doubleSpin', {'value': 10.0, 'max': MAX}),
                      ('leadingedge', 'check', {'checked': True}),
                      ('ioffsetbeg', 'intSpin', {'value': 1000, 'min': 0, 'max': MAX}),
                      ('ioffsetend', 'intSpin', {'value': 2000, 'min': 0, 'max': MAX}),
                      ('wfbinbeg', 'intSpin', {'value': 6000, 'min': 0, 'max': MAX}),
                      ('wfbinend', 'intSpin', {'value': 22000, 'min': 0, 'max': MAX})]

        def __init__(self, name):
            super().__init__(name, terminals={'Times': {'io': 'in', 'ttype': Array2d},
                                              'Waveform': {'io': 'in', 'ttype': Array2d},
                                              'Num of Hits': {'io': 'out', 'ttype': Array1d},
                                              'Index': {'io': 'out', 'ttype': Array2d},
                                              'Values': {'io': 'out', 'ttype': Array2d},
                                              'Peak Times': {'io': 'out', 'ttype': Array2d}})

        def to_operation(self, inputs, conditions={}):
            outputs = self.output_vars()

            cfdpars = {'numchs': int(self.num_chans),
                       'numhits': self.num_hits,
                       'cfd_base':  self.base,
                       'cfd_thr': self.thr,
                       'cfd_cfr':  self.cfr,
                       'cfd_deadtime':  self.deadtime,
                       'cfd_leadingedge':  self.leadingedge,
                       'cfd_ioffsetbeg':  self.ioffsetbeg,
                       'cfd_ioffsetend':  self.ioffsetend,
                       'cfd_wfbinbeg':  self.wfbinbeg,
                       'cfd_wfbinend': self.wfbinend}

            wfpeaks = psWFPeaks.WFPeaks(**cfdpars)

            def peakFinder(wts, wfs):
                peaks = wfpeaks(wfs, wts)
                return peaks

            node = gn.Map(name=self.name()+"_operation",
                          condition_needs=list(conditions.values()), inputs=list(inputs.values()), outputs=outputs,
                          func=peakFinder, parent=self.name())
            return node

    import psana.hexanode.DLDProcessor as psfDLD

    class Hexanode(CtrlNode):

        """
        Hexanode
        """

        nodeName = "Hexanode"
        uiTemplate = [('num chans', 'combo', {'values': ["5", "7"]}),
                      ('num hits', 'intSpin', {'value': 16, 'min': 1, 'max': MAX}),
                      ('verbose', 'check', {'checked': False})]

        class DLDProc():

            def __init__(self, **params):
                self.params = params
                self.proc = None

            def __call__(self, nev, nhits, pktsec):
                if self.proc is None:
                    self.proc = psfDLD.DLDProcessor(**self.params)
                x, y, r, t = zip(*self.proc.xyrt_list(nev, nhits, pktsec))
                return (np.array(x), np.array(y), np.array(r), np.array(t))

        def __init__(self, name):
            super().__init__(name, terminals={'Event Number': {'io': 'in', 'ttype': int},
                                              'Num of Hits': {'io': 'in', 'ttype': Array1d},
                                              'Peak Times': {'io': 'in', 'ttype': Array2d},
                                              'X': {'io': 'out', 'ttype': Array1d},
                                              'Y': {'io': 'out', 'ttype': Array1d},
                                              'R': {'io': 'out', 'ttype': Array1d},
                                              'T': {'io': 'out', 'ttype': Array1d}})

            self.calibcfg = '/home/seshu/dev/lcls2/psana/psana/hexanode/examples/configuration_quad.txt'
            self.calibtab = '/home/seshu/dev/lcls2/psana/psana/hexanode/examples/calibration_table_data.txt'

        def to_operation(self, inputs, conditions={}):
            outputs = self.output_vars()

            dldpars = {'numchs': int(self.num_chans),
                       'numhits': self.num_hits,
                       'verbose': self.verbose,
                       'calibtab': self.calibtab,
                       'calibcfg': self.calibcfg}

            node = gn.Map(name=self.name()+"_operation",
                          condition_needs=list(conditions.values()), inputs=list(inputs.values()), outputs=outputs,
                          func=self.DLDProc(**dldpars), parent=self.name())

            return node

except ImportError:
    pass
