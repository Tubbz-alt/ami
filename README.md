# ami
The LCLS-II online graphical analysis monitoring package.

## Download, configure, install

## Running

## User documebntation
User documentation is available [her](doc/userdoc.md)

## Design Documentation
Design documentation is available [here](doc/toplevel.md)

## Testing
Test information is available [here](doc/testing.md)

# Requirements
* Python 3.5+
* ipython
* pyzmq
* numpy

All these requirements are subject to change at any time!

# Examples
If you use the setup.py included to set this up you should now have two console
scripts available on your path: `ami-worker` and `ami-manager`. Several example
configuration files are included in the examples directory.

To run ami with three workers run the following in lcls2/ami:
```ami-worker -n 3 static://examples/worker.json```

Then start the manager:
```ami-manager```

Then, start a GUI (client):
```ami-client```

You should see an interactive QT window. There is also a convenience launcher
that when you want to run all parts of ami on a single node:
```ami-local -n 3 static://examples/worker.json```

To load a graph, add this flag to ami-local:
```-l examples/basic.ami```

To use psana a working release need to be added to the python path

# Status/To-do

7/27/18
* get more familiar with REDIS (local, global, control)
* read real XTC
* look at flink
* writeup complex XPP example with normalized background with definable time-window

6/28/18
possible projects going forward:
* cleanup setup.py
* for pickN: worker should only sum-2 per HB, even if get 4 in a HB
* integrate psana
* HB-builder timeouts
* graph-python management (big project)
* use redis for collectors
* pydm
* p4p

6/7/18
* thoughts from alan:
  * eliminate hb in favor of timestamps?
  * hb-rate operations go in the client?
  * have library of vetted building-block code that we call in any order
* Event building
  * Currently the messages sent to the collector include the id of where they came from and what heartbeat they are for
  * Use the heartbeat count to store the contributions using the collection strategy in from the graph
  * We will also have a table of eb_id completions to keep track of which workers have sent their data for a heartbeat

5/31/18
* eb
  * maybe have separate event builders and stores for heart-beat and event-count based data 
* python
  * make library of routines with parameters (not jinja string replacement)

5/24/18

next week:
* collection strategy
  * collector event builder
* python language issues:
  * string substitution
  * which vars get into store, and how?
  * need store.put, either for pickN, or for all vars?
  
EB thoughts:
* most cross-time patterns feel straightforward (e.g. stripchart can time-align on the most recent HB)
* pickN cross-time pattern feels tricky (see below)
* timeout in units of HB
* late stuff thrown away
* pickN EB
  * fuzzy
  * throws away "used" data
* only need to EB the HBs
* need buffering in the store (add level to store dict)
* don't worry about hung nodes (could consider extra "redundant" send for pickN pattern for robustness)

5/17/18

next week:
* collector gets graphs from workers, not zmq
* graph has config-id for each box, as well as overall config-id
* collector rejects data from boxes with old config-id's
* dependencies of changed boxes also get new config-id's

also added the "collector behavior" field for each output from the graph (e.g. Reduce or Null)

three major patterns for cross-time patterns:
* pickN: divide up N by number of workers, each worker sends when it reaches that number (reduce or gather)
* binned (reduce) scatter plot
* unbinned (gather) scatter plot

other patterns solved for the above:
* sum (same as pickN, but just always sum).  how to reset?
* stripchart: same as binned/unbinned 2D scatter plot
* image background subtraction (like timetool): use redis at collector and "2D" stripchart pattern to getting rolling-window average

5/10/18

Issues for next time:

* cross-time patterns: sum, average-N, stripchart, image background subtraction
* new ideas: redis for store and graph distribution (allows works to access collected data)
* what python syntax to use for cross-time patterns where values have to be fetched from feature-store?

4/26/18

* Collector event builder
* pick 1/avg N as part of the graph
* plot of A vs. B (scatter plots)
* stripcharts/scans
* feedback of data from the collector to the worker
* test speed of multiple exec's of compiled code


4/6/18

TJL created "pythonbackend" branch to explore python centric alternatives

To Decide:
* what is the best representation for "the graph"
* where does the python code associated with nodes "live"
* syntax for declaring global/posted/feature variables



2/9/18

graph building
-------------- 
How to build graphs?
* Add a simple “normalize” button to the waveform widget or image widget
* What is the best behavior for the “calculator”?
* We need to enumerate the elementary operations
* We need to only “display” explicitly tagged Results

evaluating arbitrary math expressions
    — https://ruslanspivak.com/lsbasi-part7/
    — http://newville.github.io/asteval/basics.html
    — https://stackoverflow.com/questions/2371436/evaluating-a-mathematical-expression-in-a-string
             
backend
-------
* where should we do e.g. stripchart caching?
* DOCSTRINGS
* integration with EPICS
* should we use MPI? NO
    - handle the case where the different clients are in inconsistent graph states
    - mpi event-builder (timeout)
* throttling [pick-N pattern, done on a per-heartbeat basis] (e.g. for visualizing images)
    - use top-down approach with round-robin based on heartbeat counting.  collector has to: avg/sum, scatter plot, plot vs. time/event number, plot most recent image.  
    - Use gather/reduce pattern, but implement with send/receive plus timeout (either with mpi_probe, or heartbeat counting and discard old). 
* Fix bug with first stage gather where collector will mess up if one worker is too far behind
    - make sure we don't get 'off by 1'
    - need a way to agree on the phases for the heartbeats, timing system should have some sort of number for these
* Fault tolerance (tradeoff: avoid complicating code too much which can create more failures, and cause the code to be difficult to understand)
* External interfaces:
    - hutch python - epics / json documents broker of blue sky
    - DRP feedback?
* manager needs to discover when the configuration has failed to apply on one of the workers
    
    
frontend
--------
* __how to select multiple inputs into an analysis box__
* __how to choose between two graph options (e.g. roi vs. projection)__
* Ability to edit the graph graphically.
* Visualization of the graph
* duplicate non-broken AMI functionality


other
-----
* cache worker config in manager pub so workers get it again on restart
* autosave
* read real XTC
* Minimal viable documentation ( so Dan can remember what is going on )
