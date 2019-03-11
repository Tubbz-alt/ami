
"""
Note: pytest-xprocess seems like the `approved` way to start an
external server, but not sure if it is the right thing to do

To use:
1. Inheret from AmiTBase
2. Implement one or more test() functions
"""

import pytest
import time


@pytest.mark.parametrize('start_ami', ['static'], indirect=True)
def test_complex_graph(complex_graph_file, start_ami):
    comm_handler = start_ami
    comm_handler.load(complex_graph_file)
    start = time.time()
    while comm_handler.graphVersion != comm_handler.featuresVersion:
        end = time.time()
        if end - start > 10:
            raise TimeoutError
    sig = comm_handler.fetch('signal')
    assert sig == {1: 10000.0}


@pytest.mark.parametrize('start_ami', ['psana'], indirect=True)
def test_psana_graph(psana_graph, start_ami, use_psana):

    # don't run the test if psana is not installed
    if not use_psana:
        return

    comm_handler = start_ami
    comm_handler.load(psana_graph)
    start = time.time()
    while comm_handler.graphVersion != comm_handler.featuresVersion:
        end = time.time()
        if end - start > 10:
            raise TimeoutError
    picked_cspad = comm_handler.fetch('picked')
    assert picked_cspad.shape == (6, 6)
