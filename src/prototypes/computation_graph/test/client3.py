#
# client3
#
# pick-n design pattern
#

import AMI_client as AMI
import numpy


def pickNGraph():
  graph = AMI.Graph('simple_worker_graph')
  image = AMI.DataElement('xppcspad')
  image._dataIs(numpy.ones((1024, 1024)))
  meanImage = image._worker('mean', 10)
  graph.addNode(meanImage)
  return graph

graph = pickNGraph()
AMI.printGraph(graph)
AMI.submitGraphToManager(graph) # pickle the graph and send to GraphManager

