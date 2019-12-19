import zmq
import logging
import asyncio
import zmq.asyncio
import datetime as dt
import itertools as it
import numpy as np
import pyqtgraph as pg
from qtpy.QtGui import QGridLayout
from qtpy.QtWidgets import QLCDNumber, QLabel, QWidget
from qtpy.QtCore import QRect, Qt, Signal
from ami import LogConfig


logger = logging.getLogger(LogConfig.get_package_name(__name__))

colors = ['b', 'g', 'r']
symbols = ['o', 's', 't', 'd', '+']
symbols_colors = list(it.product(symbols, colors))


class AsyncFetcher(object):

    def __init__(self, topics, terms, addr):
        self.addr = addr
        self.ctx = zmq.asyncio.Context()
        self.poller = zmq.asyncio.Poller()
        self.sockets = {}
        self.data = {}
        self.last_updated = "Last Updated: None"
        self.update_topics(topics, terms)

    @property
    def reply(self):
        if self.data.keys() == set(self.subs):
            return {name: self.data[topic] for name, topic in self.topics.items()}
        else:
            return {}

    def update_topics(self, topics, terms):
        self.topics = topics
        self.terms = terms
        self.names = list(topics.keys())
        self.subs = list(topics.values())

        for name, sock_count in self.sockets.items():
            sock, count = sock_count
            self.poller.unregister(sock)
            sock.close()

        self.sockets = {}
        self.view_subs = {}

        for term, name in terms.items():
            if name not in self.sockets:
                topic = topics[name]
                sub_topic = "view:%s:%s" % (self.addr.name, topic)
                self.view_subs[sub_topic] = topic
                sock = self.ctx.socket(zmq.SUB)
                sock.setsockopt_string(zmq.SUBSCRIBE, sub_topic)
                sock.connect(self.addr.view)
                self.poller.register(sock, zmq.POLLIN)
                self.sockets[name] = (sock, 1)  # reference count
            else:
                sock, count = self.sockets[name]
                self.sockets[name] = (sock, count+1)

    async def fetch(self):
        for sock, flag in await self.poller.poll():
            if flag != zmq.POLLIN:
                continue
            topic = await sock.recv_string()
            await sock.recv_pyobj()
            reply = await sock.recv_pyobj()
            now = dt.datetime.now()
            now = now.strftime("%H:%M:%S")
            self.last_updated = f"Last Updated: {now}"
            self.data[self.view_subs[topic]] = reply


class ScalarWidget(QLCDNumber):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super(ScalarWidget, self).__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr, **kwargs)
        self.setGeometry(QRect(320, 180, 191, 81))
        self.setDigitCount(10)

    async def update(self):
        while True:
            await self.fetcher.fetch()
            for k, v in self.fetcher.reply.items():
                self.display(v)


class AreaDetWidget(pg.ImageView):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        handles = self.roi.getHandles()
        self.roi.removeHandle(handles[1])
        self.last_updated = pg.LabelItem(parent=self.getView())
        self.pixel_value = pg.LabelItem(parent=self.getView())
        self.proxy = pg.SignalProxy(self.scene.sigMouseMoved,
                                    rateLimit=30,
                                    slot=self.cursor_hover_evt)

    def cursor_hover_evt(self, evt):
        pos = evt[0]
        pos = self.view.mapSceneToView(pos)
        if self.imageItem.image is not None:
            shape = self.imageItem.image.shape
            if 0 <= pos.x() <= shape[0] and 0 <= pos.y() <= shape[1]:
                x = int(pos.x())
                y = int(pos.y())
                z = self.imageItem.image[x, y]
                self.pixel_value.setText(f"x={x}, y={y}, z={z:.5g}")
                self.pixel_value.item.moveBy(0, 12)

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            for k, v in self.fetcher.reply.items():
                self.setImage(v)


class PixelDetWidget(pg.ImageView):

    sigClicked = Signal(object, object)

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        self.plot = pg.PlotItem()
        self.plot.hideAxis('left')
        self.plot.hideAxis('bottom')
        super().__init__(parent=parent, view=self.plot)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.last_updated = pg.LabelItem(parent=self.plot)
        self.point = self.plot.plot([0], [0], symbolBrush=(200, 0, 0), symbol='+', symbolSize=25)
        self.pixel_value = pg.LabelItem(parent=self.getView())
        self.proxy = pg.SignalProxy(self.scene.sigMouseMoved,
                                    rateLimit=30,
                                    slot=self.cursor_hover_evt)

    def cursor_hover_evt(self, evt):
        pos = evt[0]
        pos = self.plot.getViewBox().mapSceneToView(pos)
        if self.imageItem.image is not None:
            shape = self.imageItem.image.shape
            if 0 <= pos.x() <= shape[0] and 0 <= pos.y() <= shape[1]:
                x = int(pos.x())
                y = int(pos.y())
                z = self.imageItem.image[x, y]
                self.pixel_value.setText(f"x={x}, y={y}, z={z:.5g}")
                self.pixel_value.item.moveBy(0, 12)

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            for k, v in self.fetcher.reply.items():
                self.setImage(v)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            ev.accept()
            view = self.plot.getViewBox()
            if self.imageItem.image is not None:
                shape = self.imageItem.image.shape
                pos = view.mapSceneToView(ev.pos())
                if 0 <= pos.x() <= shape[0] and 0 <= pos.y() <= shape[1]:
                    x = int(pos.x())
                    y = int(pos.y())
                    self.update_cursor(x, y)
                    self.sigClicked.emit(x, y)
        else:
            ev.ignore()

    def update_cursor(self, x, y):
        self.plot.removeItem(self.point)
        self.point = self.plot.plot([x], [y], symbolBrush=(200, 0, 0), symbol='+', symbolSize=25)


class HistogramWidget(pg.GraphicsLayoutWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.plot_view = self.addPlot()
        self.plot_view.addLegend()
        self.plot = {}
        self.terms = terms
        self.last_updated = pg.LabelItem(parent=self.plot_view.getViewBox())

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                self.histogram_updated(self.fetcher.reply)

    def histogram_updated(self, data):
        i = 0

        num_terms = int(len(self.terms)/2)
        for i in range(0, num_terms):
            x = "Bins"
            y = "Counts"

            if i > 0:
                x += f".{i}"
                y += f".{i}"

            x = self.terms[x]
            y = self.terms[y]
            name = y

            x = data[x]
            y = data[y]

            if name not in self.plot:
                _, color = symbols_colors[i]
                self.plot[name] = self.plot_view.plot(x, y, name=name, brush=color,
                                                      stepMode=True, fillLevel=0)
            else:
                self.plot[name].setData(x=x, y=y)


class Histogram2DWidget(pg.GraphicsLayoutWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.setAspectLocked(True)
        self.view = self.addViewBox()
        self.view.setAspectLocked(True)

        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.terms = terms

        self.imageItem = pg.ImageItem()
        self.view.addItem(self.imageItem)

        self.plot = pg.PlotItem(viewBox=self.view)
        self.plot.showGrid(True, True)

        self.ax = self.plot.getAxis('bottom')
        self.ax.setGrid(255)
        self.ax.setZValue(1)

        self.ay = self.plot.getAxis('left')
        self.ay.setGrid(255)
        self.ay.setZValue(1)

        self.addItem(self.plot)

        self.last_updated = pg.LabelItem(parent=self.view)
        self.pixel_value = pg.LabelItem(parent=self.view)

        self.proxy = pg.SignalProxy(self.scene().sigMouseMoved,
                                    rateLimit=30,
                                    slot=self.cursor_hover_evt)

        self.xbins = None
        self.ybins = None

    def cursor_hover_evt(self, evt):
        pos = evt[0]
        pos = self.view.mapSceneToView(pos)

        if self.imageItem.image is not None:
            shape = self.imageItem.image.shape

            if 0 <= pos.x() <= shape[0] and \
               0 <= pos.y() <= shape[1]:
                idxx = int(pos.x())
                idxy = int(pos.y())
                x = self.xbins[idxx]
                y = self.ybins[idxy]
                z = self.imageItem.image[idxx, idxy]
                self.pixel_value.setText(f"x={x:.5g}, y={y:.5g}, z={z:.5g}")
                self.pixel_value.item.moveBy(0, 12)

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                data = self.fetcher.reply

                xbins = self.terms['XBins']
                ybins = self.terms['YBins']
                counts = self.terms['Counts']

                self.xbins = data[xbins]
                self.ybins = data[ybins]
                counts = data[counts]
                xscale = (self.xbins[-1] - self.xbins[0])/self.xbins.shape
                yscale = (self.ybins[-1] - self.ybins[0])/self.ybins.shape

                self.ax.setRange(self.xbins[0], self.xbins[-1])
                self.ax.setScale(xscale[0])

                self.ay.setRange(self.ybins[0], self.ybins[-1])
                self.ay.setScale(yscale[0])

                # self.view.setLimits(xMin=0, xMax=len(self.xbins),
                #                     yMin=0, yMax=len(self.ybins),
                #                     minXRange=xscale[0], minYRange=yscale[0])

                self.imageItem.setImage(counts,
                                        pos=(self.xbins[0], self.ybins[0]),
                                        scale=(xscale[0], yscale[0]))


class ScatterWidget(pg.GraphicsLayoutWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.plot_view = self.addPlot()
        self.plot_view.addLegend()
        self.plot = {}
        self.terms = terms
        self.last_updated = pg.LabelItem(parent=self.plot_view.getViewBox())

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                self.scatter_updated(self.fetcher.reply)

    def scatter_updated(self, data):
        num_terms = int(len(self.terms)/2)
        for i in range(0, num_terms):
            x = "X"
            y = "Y"
            if i > 0:
                x += ".%d" % i
                y += ".%d" % i
            x = self.terms[x]
            y = self.terms[y]
            name = " vs ".join((y, x))
            x = data[x]
            y = data[y]

            if name not in self.plot:
                self.plot[name] = pg.ScatterPlotItem(name=name)
                self.plot_view.addItem(self.plot[name])
                self.plot_view.addLegend().addItem(self.plot[name], name=name)
            scatter = self.plot[name]
            symbol, color = symbols_colors[i]
            scatter.setData(x=x, y=y, symbol=symbol, brush=color)


class WaveformWidget(pg.GraphicsLayoutWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.plot_view = self.addPlot()
        self.plot_view.addLegend()
        self.plot = {}
        self.terms = terms
        self.last_updated = pg.LabelItem(parent=self.plot_view.getViewBox())

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                self.waveform_updated(self.fetcher.reply)

    def waveform_updated(self, data):
        i = 0
        for term, name in self.terms.items():
            if name not in self.plot:
                symbol, color = symbols_colors[i]
                i += 1
                self.plot[name] = self.plot_view.plot(y=np.array(data[name]), name=name,
                                                      symbol=symbol, symbolBrush=color)
            else:
                self.plot[name].setData(y=np.array(data[name]))


class LineWidget(pg.GraphicsLayoutWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.plot_view = self.addPlot()
        self.plot_view.addLegend()
        self.plot = {}
        self.terms = terms
        self.last_updated = pg.LabelItem(parent=self.plot_view.getViewBox())

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                self.line_updated(self.fetcher.reply)

    def line_updated(self, data):
        num_terms = int(len(self.terms)/2)
        for i in range(0, num_terms):
            x = "X"
            y = "Y"
            if i > 0:
                x += ".%d" % i
                y += ".%d" % i
            x = self.terms[x]
            y = self.terms[y]
            name = " vs ".join((y, x))
            x = data[x]
            y = data[y]
            if name not in self.plot:
                symbol, color = symbols_colors[i]
                i += 1
                self.plot[name] = self.plot_view.plot(x=x, y=y, name=name, symbol=symbol, symbolBrush=color)
            else:
                self.plot[name].setData(x=x, y=y)


class ArrayWidget(QWidget):

    def __init__(self, topics, terms, addr, parent=None, **kwargs):
        super().__init__(parent)
        self.fetcher = AsyncFetcher(topics, terms, addr)
        self.terms = terms
        self.update_rate = kwargs.get('update_rate', 30)
        self.grid = QGridLayout(self)
        self.table = pg.TableWidget()
        self.last_updated = QLabel(parent=self)
        self.grid.addWidget(self.table, 0, 0)
        self.grid.setRowStretch(0, 10)
        self.grid.addWidget(self.last_updated, 1, 0)

    async def update(self):
        while True:
            await self.fetcher.fetch()
            self.last_updated.setText(self.fetcher.last_updated)
            if self.fetcher.reply:
                self.array_updated(self.fetcher.reply)
            await asyncio.sleep(self.update_rate)

    def array_updated(self, data):
        for term, name in self.terms.items():
            self.table.setData(data[name])
