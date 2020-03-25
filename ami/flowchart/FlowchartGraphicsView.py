from pyqtgraph.Qt import QtGui, QtCore, QtWidgets
from pyqtgraph.widgets.GraphicsView import GraphicsView
from pyqtgraph.graphicsItems.ViewBox import ViewBox
from pyqtgraph import GridItem, GraphicsWidget
from ami.flowchart.Node import NodeGraphicsItem, find_nearest
from ami.flowchart.library.common import SourceNode


def clamp(pos):
    pos = [find_nearest(pos.x()), find_nearest(pos.y())]
    pos[0] = max(min(pos[0], 5e3), 0)
    pos[1] = max(min(pos[1], 5e3), -900)
    return QtCore.QPointF(*pos)


class Rect(GraphicsWidget):
    # Copyright 2015-2019 Ilgar Lunin, Pedro Cabrera
    # taken from pyflow
    def __init__(self, view, mouseDownPos, backgroundColor, pen):
        super().__init__()
        self.view = view
        self.view.addItem(self)
        self.__backgroundColor = backgroundColor
        self.__pen = pen
        self.__mouseDownPos = mouseDownPos
        self.setPos(self.__mouseDownPos)
        self.resize(0, 0)

    def collidesWithItem(self, item, selectFullyIntersectedItems=True):
        if selectFullyIntersectedItems:
            return self.sceneBoundingRect().contains(item.sceneBoundingRect())
        return super().collidesWithItem(item)

    def setDragPoint(self, dragPoint):
        topLeft = QtCore.QPointF(self.__mouseDownPos)
        bottomRight = QtCore.QPointF(dragPoint)
        if dragPoint.x() < self.__mouseDownPos.x():
            topLeft.setX(dragPoint.x())
            bottomRight.setX(self.__mouseDownPos.x())
        if dragPoint.y() < self.__mouseDownPos.y():
            topLeft.setY(dragPoint.y())
            bottomRight.setY(self.__mouseDownPos.y())
        self.setPos(topLeft)
        self.resize(max(bottomRight.x() - topLeft.x(), 100),
                    max(bottomRight.y() - topLeft.y(), 100))

    def paint(self, painter, option, widget):
        rect = self.windowFrameRect()
        painter.setBrush(self.__backgroundColor)
        painter.setPen(self.__pen)
        painter.drawRect(rect)

    def destroy(self):
        self.view.removeItem(self)


class CommentName(GraphicsWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.label = QtWidgets.QGraphicsTextItem("Enter comment here", parent=self)
        self.label.setTextInteractionFlags(QtCore.Qt.TextEditorInteraction)
        self.setGraphicsItem(self.label)


class CommentRect(Rect):
    # Copyright 2015-2019 Ilgar Lunin, Pedro Cabrera
    # taken from pyflow

    def __init__(self, view, mouseDownPos):
        backgroundColor = QtGui.QColor(100, 100, 255, 50)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255), 1.0, QtCore.Qt.DashLine)
        super().__init__(view, mouseDownPos, backgroundColor, pen)
        self.setZValue(-1)
        flags = self.ItemIsMovable | self.ItemSendsGeometryChanges
        self.setFlags(flags)
        self.headerLayout = QtGui.QGraphicsLinearLayout(QtCore.Qt.Horizontal)
        self.commentName = CommentName(parent=self)
        self.headerLayout.addItem(self.commentName)
        self.buildMenu()
        self.childNodes = set()
        self.movingChild = False

    def mouseMoveEvent(self, ev):
        ev.accept()
        pos = self.mapToScene(ev.pos())
        for child in self.childNodes:
            if child.sceneBoundingRect().contains(pos):
                self.movingChild = True
                child.setPos(self.mapToScene(ev.pos()))
                break

        if not self.movingChild:
            old_pos = self.pos()
            super().mouseMoveEvent(ev)
            new_pos = self.pos()
            diff = new_pos - old_pos

            for child in self.childNodes:
                child.moveBy(*diff)

    def mouseReleaseEvent(self, ev):
        ev.accept()
        self.setPos(clamp(self.pos()))

        pos = self.mapToScene(ev.pos())
        for child in self.childNodes:
            child.setPos(clamp(child.pos()))

            if not self.movingChild and child.sceneBoundingRect().contains(pos):
                child.setSelected(True)

        self.movingChild = False
        super().mouseReleaseEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            boundingRect = self.boundingRect()
            width = boundingRect.width()
            height = boundingRect.height()
            rect = QtCore.QRectF(width - 50, height - 50, 50, 50)
            if rect.contains(ev.pos()):
                self.view.commentRect = self
                ev.ignore()
            else:
                ev.accept()
                super().mousePressEvent(ev)

        elif ev.button() == QtCore.Qt.RightButton:
            ev.accept()
            pos = ev.screenPos()
            self.menu.popup(QtCore.QPoint(pos.x(), pos.y()))

    def nodeCreated(self, node):
        item = node.graphicsItem()
        if self.collidesWithItem(item):
            self.childNodes.add(item)

    def buildMenu(self):
        self.menu = QtGui.QMenu()
        self.menu.setTitle("Comment")
        self.menu.addAction("Remove Comment", self.destroy)


class SelectionRect(Rect):
    # Copyright 2015-2019 Ilgar Lunin, Pedro Cabrera
    # taken from pyflow

    def __init__(self, view, mouseDownPos):
        backgroundColor = QtGui.QColor(100, 100, 100, 50)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255), 1.0, QtCore.Qt.DashLine)
        super().__init__(view, mouseDownPos, backgroundColor, pen)


class FlowchartGraphicsView(GraphicsView):

    sigHoverOver = QtCore.Signal(object)
    sigClicked = QtCore.Signal(object)

    def __init__(self, widget, *args):
        super().__init__(*args, useOpenGL=False, background=0.75)
        self.widget = widget
        self.setAcceptDrops(True)
        self._vb = FlowchartViewBox(widget, lockAspect=True, invertY=True)
        self.setCentralItem(self._vb)
        self.setRenderHint(QtGui.QPainter.Antialiasing, True)

    def viewBox(self):
        return self._vb

    def dragEnterEvent(self, ev):
        ev.accept()


class FlowchartViewBox(ViewBox):

    def __init__(self, widget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget = widget
        self.chart = widget.chart

        self.setLimits(minXRange=200, minYRange=200,
                       xMin=-1000, yMin=-1000, xMax=5.2e3, yMax=5.2e3)
        self.addItem(GridItem())
        self.setAcceptDrops(True)
        self.setRange(xRange=(0, 800), yRange=(0, 800))
        self.mouseMode = "Pan"

        self.selectionRect = None
        self.selected_nodes = []

        self.copy = False
        self.paste_pos = None

        self.commentRect = None
        self.commentRects = []

    def setMouseMode(self, mode):
        assert mode in ["Select", "Pan", "Comment"]
        self.mouseMode = mode

    def getMenu(self, ev):
        # called by ViewBox to create a new context menu
        self._fc_menu = QtGui.QMenu()
        self._subMenus = self.getContextMenus(ev)
        for menu in self._subMenus:
            self._fc_menu.addMenu(menu)

        if self.selected_nodes:
            self.selected_node_menu = QtGui.QMenu("Selection")
            if not self.copy:
                self.selected_node_menu.addAction("Copy", self.copySelectedNodes)
            else:
                self.selected_node_menu.addAction("Paste", self.pasteSelectedNodes)
                self.paste_pos = ev.pos()
            self.selected_node_menu.addAction("Delete", self.deleteSelectedNodes)
            # self.selected_node_menu.addAction("Make subgraph", self.makesubgraph)
            self._fc_menu.addMenu(self.selected_node_menu)

        return self._fc_menu

    def copySelectedNodes(self):
        self.copy = True

    def pasteSelectedNodes(self):
        # TODO figure out right positions and preserve topology?
        pos = self.mapToView(self.paste_pos)

        for node in self.selected_nodes:
            self.widget.chart.createNode(type(node).__name__, pos=pos)
            pos += QtCore.QPointF(200, 0)

    def deleteSelectedNodes(self):
        for node in self.selected_nodes:
            node.close()

    def getContextMenus(self, ev):
        # called by scene to add menus on to someone else's context menu
        sourceMenu = self.widget.buildSourceMenu(ev.scenePos())
        sourceMenu.setTitle("Add Source")
        operationMenu = self.widget.buildOperationMenu(ev.scenePos())
        operationMenu.setTitle("Add Operation")
        return [sourceMenu, operationMenu, ViewBox.getMenu(self, ev)]

    def decode_data(self, arr):
        data = []
        item = {}

        ds = QtCore.QDataStream(arr)
        while not ds.atEnd():
            ds.readInt32()
            ds.readInt32()

            map_items = ds.readInt32()
            for i in range(map_items):

                key = ds.readInt32()

                value = QtCore.QVariant()
                ds >> value
                item[QtCore.Qt.ItemDataRole(key)] = value

                data.append(item)

        return data

    def mouseDragEvent(self, ev):
        ev.accept()

        if self.mouseMode == "Pan":
            super().mouseDragEvent(ev)

        elif self.mouseMode == "Select":
            if ev.isStart():
                self.selectionRect = SelectionRect(self, self.mapToView(ev.buttonDownPos()))

            if self.selectionRect:
                self.selectionRect.setDragPoint(self.mapToView(ev.pos()))

            if ev.isFinish():
                self.selected_nodes = []
                for item in self.allChildren():
                    if not isinstance(item, NodeGraphicsItem):
                        continue
                    if self.selectionRect.collidesWithItem(item):
                        item.node.recolor("selected")
                        self.selected_nodes.append(item.node)

                self.copy = False
                self.selectionRect.destroy()
                self.selectionRect = None

        elif self.mouseMode == "Comment":
            if ev.isStart() and self.commentRect is None:
                pos = clamp(self.mapToView(ev.buttonDownPos()))
                self.commentRect = CommentRect(self, pos)
                self.chart.sigNodeCreated.connect(self.commentRect.nodeCreated)

            if self.commentRect:
                pos = clamp(self.mapToView(ev.pos()))
                self.commentRect.setDragPoint(pos)

            if ev.isFinish():
                self.commentRects.append(self.commentRect)

                for item in self.allChildren():
                    if isinstance(item, NodeGraphicsItem) and self.commentRect.collidesWithItem(item):
                        self.commentRect.childNodes.add(item)

                self.commentRect = None

    def mousePressEvent(self, ev):
        ev.accept()
        super().mousePressEvent(ev)

        # if we have selected nodes, restore their coloring to normal
        if ev.button() == QtCore.Qt.LeftButton:
            for node in self.selected_nodes:
                node.recolor()

    def dropEvent(self, ev):
        if ev.mimeData().hasFormat('application/x-qabstractitemmodeldatalist'):
            arr = ev.mimeData().data('application/x-qabstractitemmodeldatalist')
            node = self.decode_data(arr)[0][0].value()
            try:
                self.widget.chart.createNode(node, pos=self.mapToView(ev.pos()))
                ev.accept()
                return
            except KeyError:
                pass

            try:
                node_type = self.widget.chart.source_library.getSourceType(node)
                if node not in self.widget.chart._graph:
                    node = SourceNode(name=node, terminals={'Out': {'io': 'out', 'ttype': node_type}})
                    self.widget.chart.createNode(node_type, name=node.name(), node=node, pos=self.mapToView(ev.pos()))
                    ev.accept()
                    return
            except KeyError:
                pass

        else:
            ev.ignore()
