#
# globalCollector1.py
#

import AMI_server as AMI

print('read work graph')
graph = AMI.workerGraph()
graph._receiveLocalCollectorData('localCollector2.dat')

result = graph._doGlobalCollector()
print('globalCollector result is', result)

graph._transmitGlobalCollectorData('globalCollector2.dat')


