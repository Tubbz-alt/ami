# -*- coding: utf-8 -*-
from pyqtgraph.Qt import QtCore, QtGui
from pyqtgraph.graphicsItems.GraphicsObject import GraphicsObject
from pyqtgraph import functions as fn
from pyqtgraph.Point import Point
import weakref


class Terminal(object):
    def __init__(self, node, name, io, type=object, pos=None, removable=False):
        """
        Construct a new terminal.

        ==============  =================================================================================
        **Arguments:**
        node            the node to which this terminal belongs
        name            string, the name of the terminal
        io              'in', 'out', or 'condition'
        typ             type terminal expects/returns
        pos             [x, y], the position of the terminal within its node's boundaries
        removable       (bool) Whether the terminal can be removed by the user
        ==============  =================================================================================
        """
        self._io = io
        self._node = weakref.ref(node)
        self._name = name
        self._removable = removable
        self._connections = {}
        self._type = type
        self._propagatedType = False

        self._graphicsItem = TerminalGraphicsItem(self, parent=self._node().graphicsItem())

        self._value = None
        self.recolor()

    def setOpts(self, **opts):
        self._removable = opts.get('removable', self._removable)
        self._type = opts.get('type', self._type)

    def connected(self, term):
        """
        Called whenever this terminal has been connected to another.
        (note--this function is called on both terminals)
        """
        self.node().connected(self, term)

    def disconnected(self, term):
        """
        Called whenever this terminal has been disconnected from another.
        (note--this function is called on both terminals)
        """
        self.node().disconnected(self, term)

    def type(self):
        return self._type

    def setType(self, type):
        self._type = type

    def value(self, term=None):
        """Return the value this terminal provides for the connected terminal"""
        return self._value

    def connections(self):
        return self._connections

    def node(self):
        return self._node()

    def isInput(self):
        return self._io == 'in'

    def isOutput(self):
        return self._io == 'out'

    def isCondition(self):
        return self._io == "condition"

    def isRemovable(self):
        return self._removable

    def name(self):
        return self._name

    def graphicsItem(self):
        return self._graphicsItem

    def isConnected(self):
        return len(self.connections()) > 0

    def connectedTo(self, term):
        return term in self.connections()

    def hasInput(self):
        for t in self.connections():
            if t.isOutput():
                return True
        return False

    def inputTerminals(self):
        """Return the terminal(s) that give input to this one."""
        return [t for t in self.connections() if t.isOutput()]

    def dependentNodes(self):
        """Return the list of nodes which receive input from this terminal."""
        return set([t.node() for t in self.connections() if t.isInput()])

    def connectTo(self, term, connectionItem=None):
        try:
            if self.connectedTo(term):
                raise Exception('Already connected')
            if term is self:
                raise Exception('Not connecting terminal to self')
            if term.node() is self.node():
                raise Exception("Can't connect to terminal on same node.")
            for t in [self, term]:
                if t.isInput() and len(t.connections()) > 0:
                    raise Exception(
                        "Cannot connect %s <-> %s: Terminal %s is already connected to %s \
                        (and does not allow multiple connections)" % (self, term, t, list(t.connections().keys())))
            self.propagateType(term)
            if not checkType(self.type(), term.type()):
                raise Exception("Invalid types. Expected: %s Got: %s", self.type(), term.type())
        except Exception:
            if connectionItem is not None:
                connectionItem.close()
            raise

        if connectionItem is None:
            connectionItem = ConnectionItem(self.graphicsItem(), term.graphicsItem())
            self.graphicsItem().getViewBox().addItem(connectionItem)
        self._connections[term] = connectionItem
        term._connections[self] = connectionItem

        self.recolor()

        self.connected(term)
        term.connected(self)

        return connectionItem

    def propagateType(self, term):
        if self.isCondition() or term.isCondition():
            return

        if self.type() == object:
            self.setType(term.type())
            terms = self.node().terminals
            if self.isInput():
                if 'Out' in terms and terms["Out"].type() == object:
                    terms["Out"].setType(term.type())
                    terms["Out"]._propagatedType = True
            elif self.isOutput():
                if 'In' in terms:
                    terms["In"].setType(term.type())
                    terms["In"]._propagatedType = True
            self._propagatedType = True

        elif term.type() == object:
            term.setType(self.type())
            terms = term.node().terminals
            if term.isInput():
                if 'Out' in terms and terms["Out"].type() == object:
                    terms["Out"].setType(self.type())
                    terms["Out"]._propagatedType = True
            elif term.isOutput():
                if 'In' in terms:
                    terms["In"].setType(term.type())
                    terms["In"]._propagatedType = True

            term._propagatedType = True

    def disconnectFrom(self, term):
        if not self.connectedTo(term):
            return
        item = self._connections[term]
        item.close()
        del self._connections[term]
        del term._connections[self]
        self.recolor()
        term.recolor()

        # if self._propagatedType:
        #     self.term.setType(object)

        self.disconnected(term)
        term.disconnected(self)

    def disconnectAll(self):
        for t in list(self._connections.keys()):
            self.disconnectFrom(t)

    def recolor(self, color=None, recurse=True):
        if color is None:
            if not self.isConnected():
                # disconnected terminals are black
                color = QtGui.QColor(0, 0, 0)
            elif self.isInput() and not self.hasInput():
                # input terminal with no connected output terminals
                color = QtGui.QColor(200, 200, 0)
            elif self._value is None or fn.eq(self._value, {}):
                # terminal is connected but has no data (possibly due to processing error)
                color = QtGui.QColor(255, 255, 255)
            elif self.valueIsAcceptable() is None:
                # terminal has data, but it is unknown if the data is ok
                color = QtGui.QColor(200, 200, 0)
            elif self.valueIsAcceptable() is True:
                # terminal has good input, all ok
                color = QtGui.QColor(0, 200, 0)
            else:
                # terminal has bad input
                color = QtGui.QColor(200, 0, 0)
        self.graphicsItem().setBrush(QtGui.QBrush(color))

        if recurse:
            for t in self.connections():
                t.recolor(color, recurse=False)

    def __repr__(self):
        return "<Terminal %s.%s>" % (str(self.node().name()), str(self.name()))

    def __hash__(self):
        return id(self)

    def close(self):
        self.disconnectAll()
        item = self.graphicsItem()
        if item.scene() is not None:
            item.scene().removeItem(item)

    def saveState(self):
        return {
            'io': self._io,
            'removable': self._removable,
        }


class TerminalGraphicsItem(GraphicsObject):

    def __init__(self, term, parent=None):
        self.term = term
        GraphicsObject.__init__(self, parent)
        self.brush = fn.mkBrush(0, 0, 0)
        self.box = QtGui.QGraphicsRectItem(0, 0, 10, 10, self)
        self.label = QtGui.QGraphicsTextItem(self.term.name(), self)
        self.label.scale(0.7, 0.7)
        self.newConnection = None
        self.setFiltersChildEvents(True)  # to pick up mouse events on the rectitem
        self.setZValue(1)
        self.menu = None

    def setBrush(self, brush):
        self.brush = brush
        self.box.setBrush(brush)

    def disconnect(self, target):
        self.term.disconnectFrom(target.term)

    def boundingRect(self):
        br = self.box.mapRectToParent(self.box.boundingRect())
        lr = self.label.mapRectToParent(self.label.boundingRect())
        return br | lr

    def paint(self, p, *args):
        pass

    def setAnchor(self, x, y):
        pos = QtCore.QPointF(x, y)
        self.anchorPos = pos
        br = self.box.mapRectToParent(self.box.boundingRect())
        lr = self.label.mapRectToParent(self.label.boundingRect())

        if self.term.isInput() or self.term.isCondition():
            self.box.setPos(pos.x(), pos.y()-br.height()/2.)
            self.label.setPos(pos.x() + br.width(), pos.y() - lr.height()/2.)
        else:
            self.box.setPos(pos.x()-br.width(), pos.y()-br.height()/2.)
            self.label.setPos(pos.x()-br.width()-lr.width(), pos.y()-lr.height()/2.)
        self.updateConnections()

    def updateConnections(self):
        for t, c in self.term.connections().items():
            c.updateLine()

    def mousePressEvent(self, ev):
        # ev.accept()
        ev.ignore()  # necessary to allow click/drag events to process correctly

    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            ev.accept()
            self.label.setFocus(QtCore.Qt.MouseFocusReason)
        elif ev.button() == QtCore.Qt.RightButton:
            ev.accept()
            self.raiseContextMenu(ev)

    def raiseContextMenu(self, ev):
        # only raise menu if this terminal is removable
        menu = self.getMenu()
        menu = self.scene().addParentContextMenus(self, menu, ev)
        pos = ev.screenPos()
        menu.popup(QtCore.QPoint(pos.x(), pos.y()))

    def getMenu(self):
        if self.menu is None:
            self.menu = QtGui.QMenu()
            self.menu.setTitle("Terminal")

            disconAct = QtGui.QAction("Disconnect", self.menu)
            disconAct.triggered.connect(lambda: self.term.disconnectFrom(self.term.inputTerminals()[0]))
            self.menu.addAction(disconAct)
            self.menu.disconAct = disconAct
            if not self.term.isConnected():
                disconAct.setEnabled(False)

            if self.term.isRemovable():
                remAct = QtGui.QAction("Remove terminal", self.menu)
                remAct.triggered.connect(self.removeSelf)
                self.menu.addAction(remAct)
                self.menu.remAct = remAct

        return self.menu

    def removeSelf(self):
        self.term.node().removeTerminal(self.term)

    def mouseDragEvent(self, ev):
        if ev.button() != QtCore.Qt.LeftButton:
            ev.ignore()
            return

        ev.accept()
        if ev.isStart():
            if self.newConnection is None:
                self.newConnection = ConnectionItem(self)
                self.getViewBox().addItem(self.newConnection)

            self.newConnection.setTarget(self.mapToView(ev.pos()))
        elif ev.isFinish():
            if self.newConnection is not None:
                items = self.scene().items(ev.scenePos())
                gotTarget = False
                for i in items:
                    if isinstance(i, TerminalGraphicsItem):
                        self.newConnection.setTarget(i)
                        try:
                            self.term.connectTo(i.term, self.newConnection)
                            gotTarget = True
                        except Exception as e:
                            self.scene().removeItem(self.newConnection)
                            self.newConnection = None
                            raise e
                        break

                if not gotTarget:
                    self.newConnection.close()
                self.newConnection = None
        else:
            if self.newConnection is not None:
                self.newConnection.setTarget(self.mapToView(ev.pos()))

    def hoverEvent(self, ev):
        if not ev.isExit() and ev.acceptDrags(QtCore.Qt.LeftButton):
            # we don't use the click, but we also don't want anyone else to use it.
            ev.acceptClicks(QtCore.Qt.LeftButton)
            ev.acceptClicks(QtCore.Qt.RightButton)
            self.box.setBrush(fn.mkBrush('w'))
        else:
            self.box.setBrush(self.brush)
        self.update()

    def connectPoint(self):
        # return the connect position of this terminal in view coords
        return self.mapToView(self.mapFromItem(self.box, self.box.boundingRect().center()))

    def nodeMoved(self):
        for t, item in self.term.connections().items():
            item.updateLine()


class ConnectionItem(GraphicsObject):

    def __init__(self, source, target=None):
        GraphicsObject.__init__(self)
        self.setFlags(
            self.ItemIsSelectable |
            self.ItemIsFocusable
        )
        self.source = source
        self.target = target
        self.length = 0
        self.hovered = False
        self.path = None
        self.shapePath = None
        self.style = {
            'shape': 'cubic',
            'color': (100, 100, 250),
            'width': 10.0,
            'hoverColor': (150, 150, 250),
            'hoverWidth': 1.0,
            'selectedColor': (200, 200, 0),
            'selectedWidth': 3.0,
            }
        self.source.getViewBox().addItem(self)
        self.updateLine()
        self.setZValue(0)

    def close(self):
        if self.scene() is not None:
            self.scene().removeItem(self)

    def setTarget(self, target):
        self.target = target
        self.updateLine()

    def setStyle(self, **kwds):
        self.style.update(kwds)
        if 'shape' in kwds:
            self.updateLine()
        else:
            self.update()

    def updateLine(self):
        start = Point(self.source.connectPoint())
        if isinstance(self.target, TerminalGraphicsItem):
            stop = Point(self.target.connectPoint())
        elif isinstance(self.target, QtCore.QPointF):
            stop = Point(self.target)
        else:
            return
        self.prepareGeometryChange()

        self.path = self.generatePath(start, stop)
        self.shapePath = None
        self.update()

    def generatePath(self, start, stop):
        path = QtGui.QPainterPath()
        path.moveTo(start)
        if self.style['shape'] == 'line':
            path.lineTo(stop)
        elif self.style['shape'] == 'cubic':
            path.cubicTo(Point(stop.x(), start.y()), Point(start.x(), stop.y()), Point(stop.x(), stop.y()))
        else:
            raise Exception('Invalid shape "%s"; options are "line" or "cubic"' % self.style['shape'])
        return path

    def keyPressEvent(self, ev):
        if not self.isSelected():
            ev.ignore()
            return

        if ev.key() == QtCore.Qt.Key_Delete or ev.key() == QtCore.Qt.Key_Backspace:
            self.source.disconnect(self.target)
            ev.accept()
        else:
            ev.ignore()

    def mousePressEvent(self, ev):
        ev.ignore()

    def mouseClickEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            ev.accept()
            sel = self.isSelected()
            self.setSelected(True)
            self.setFocus()
            if not sel and self.isSelected():
                self.update()

    def hoverEvent(self, ev):
        if (not ev.isExit()) and ev.acceptClicks(QtCore.Qt.LeftButton):
            self.hovered = True
        else:
            self.hovered = False
        self.update()

    def boundingRect(self):
        return self.shape().boundingRect()

    def viewRangeChanged(self):
        self.shapePath = None
        self.prepareGeometryChange()

    def shape(self):
        if self.shapePath is None:
            if self.path is None:
                return QtGui.QPainterPath()
            stroker = QtGui.QPainterPathStroker()
            px = self.pixelWidth()
            stroker.setWidth(px*8)
            self.shapePath = stroker.createStroke(self.path)
        return self.shapePath

    def paint(self, p, *args):
        if self.isSelected():
            p.setPen(fn.mkPen(self.style['selectedColor'], width=self.style['selectedWidth']))
        else:
            if self.hovered:
                p.setPen(fn.mkPen(self.style['hoverColor'], width=self.style['hoverWidth']))
            else:
                p.setPen(fn.mkPen(self.style['color'], width=self.style['width']))

        p.drawPath(self.path)


def checkType(t1, t2):
    if not type(t1) == tuple:
        t1 = (t1, )

    if not type(t2) == tuple:
        t2 = (t2, )

    t1 = set(t1)
    t2 = set(t2)

    if t1.intersection(t2) or t2.intersection(t1):
        return True
    elif object in t1 or object in t2:
        return True

    return False
