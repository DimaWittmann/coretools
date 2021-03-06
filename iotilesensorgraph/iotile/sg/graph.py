"""Sensor Graph main object."""

from collections import deque
import logging
from pkg_resources import iter_entry_points
from toposort import toposort_flatten
from iotile.core.exceptions import ArgumentError
from iotile.core.hw.reports import IOTileReading
from .node_descriptor import parse_node_descriptor
from .slot import SlotIdentifier
from .stream import DataStream
from .known_constants import config_fast_tick_secs, config_tick1_secs, config_tick2_secs
from .exceptions import NodeConnectionError, ProcessingFunctionError, ResourceUsageError


class SensorGraph(object):
    """A graph based data processing engine.

    Args:
        sensor_log (SensorLog): The sensor log where we should store our
            data
        model (DeviceModel): The device model to use for limiting our
            available resources
        enforce_limits (bool): Enforce the sensor graph size limits imposed
            by the chosen device model.  This can be useful for getting early
            failures on sensor graphs that cannot work on a given device model.
            Defaults to False.
    """

    def __init__(self, sensor_log, model=None, enforce_limits=False):
        self.roots = []
        self.nodes = []
        self.streamers = []

        self.constant_database = {}
        self.metadata_database = {}
        self.config_database = {}

        self.sensor_log = sensor_log
        self.model = model

        self._manually_triggered_streamers = set()
        self._logger = logging.getLogger(__name__)

        if enforce_limits:
            if model is None:
                raise ArgumentError("You must pass a device model if you set enforce_limits=True")

            self._max_nodes = model.get(u'max_nodes')
            self._max_streamers = model.get(u'max_streamers')
        else:
            self._max_nodes = None
            self._max_streamers = None

    def clear(self):
        """Clear all nodes from this sensor_graph.

        This function is equivalent to just creating a new SensorGraph() object
        from scratch.  It does not clear any data from the SensorLog, however.
        """

        self.roots = []
        self.nodes = []
        self.streamers = []

        self.constant_database = {}
        self.metadata_database = {}
        self.config_database = {}

    def add_node(self, node_descriptor):
        """Add a node to the sensor graph based on the description given.

        The node_descriptor must follow the sensor graph DSL and describe
        a node whose input nodes already exist.

        Args:
            node_descriptor (str): A description of the node to be added
                including its inputs, triggering conditions, processing function
                and output stream.
        """

        if self._max_nodes is not None and len(self.nodes) >= self._max_nodes:
            raise ResourceUsageError("Maximum number of nodes exceeded", max_nodes=self._max_nodes)

        node, inputs, processor = parse_node_descriptor(node_descriptor, self.model)

        in_root = False

        for i, input_data in enumerate(inputs):
            selector, trigger = input_data

            walker = self.sensor_log.create_walker(selector)

            # Constant walkers begin life initialized to 0 so they always read correctly
            if walker.selector.inexhaustible:
                walker.reading = IOTileReading(walker.selector.as_stream(), 0xFFFFFFFF, 0)

            node.connect_input(i, walker, trigger)

            if selector.input and not in_root:
                self.roots.append(node)
                in_root = True  # Make sure we only add to root list once
            else:
                found = False
                for other in self.nodes:
                    if selector.matches(other.stream):
                        other.connect_output(node)
                        found = True

                if not found and selector.buffered:
                    raise NodeConnectionError("Node has input that refers to another node that has not been created yet", node_descriptor=node_descriptor, input_selector=str(selector), input_index=i)

        # Also make sure we add this node's output to any other existing node's inputs
        # this is important for constant nodes that may be written from multiple places
        # FIXME: Make sure when we emit nodes, they are topologically sorted
        for other_node in self.nodes:
            for selector, trigger in other_node.inputs:
                if selector.matches(node.stream):
                    node.connect_output(other_node)

        # Find and load the processing function for this node
        func = self.find_processing_function(processor)
        if func is None:
            raise ProcessingFunctionError("Could not find processing function in installed packages", func_name=processor)

        node.set_func(processor, func)
        self.nodes.append(node)

    def add_config(self, slot, config_id, config_type, value):
        """Add a config variable assignment to this sensor graph.

        Args:
            slot (SlotIdentifier): The slot identifier that this config
                variable is assigned to.
            config_id (int): The 16-bit id of this config_id
            config_type (str): The type of the config variable, currently
                supported are fixed width integer types, strings and binary
                blobs.
            value (str|int|bytes): The value to assign to the config variable.
        """

        if slot not in self.config_database:
            self.config_database[slot] = {}

        self.config_database[slot][config_id] = (config_type, value)

    def add_streamer(self, streamer):
        """Add a streamer to this sensor graph.

        Args:
            streamer (DataStreamer): The streamer we want to add
        """

        if self._max_streamers is not None and len(self.streamers) >= self._max_streamers:
            raise ResourceUsageError("Maximum number of streamers exceeded", max_streamers=self._max_streamers)

        streamer.link_to_storage(self.sensor_log)
        streamer.index = len(self.streamers)

        self.streamers.append(streamer)

    def add_constant(self, stream, value):
        """Store a constant value for use in this sensor graph.

        Constant assignments occur after all sensor graph nodes have been
        allocated since they must be propogated to all appropriate virtual
        stream walkers.

        Args:
            stream (DataStream): The constant stream to assign the value to
            value (int): The value to assign.
        """

        if stream in self.constant_database:
            raise ArgumentError("Attempted to set the same constant twice", stream=stream, old_value=self.constant_database[stream], new_value=value)

        self.constant_database[stream] = value

    def add_metadata(self, name, value):
        """Attach a piece of metadata to this sensorgraph.

        Metadata is not used during the simulation of a sensorgraph but allows
        it to convey additional context that may be used during code
        generation.  For example, associating an `app_tag` with a sensorgraph
        allows the snippet code generator to set that app_tag on a device when
        programming the sensorgraph.

        Arg:
            name (str): The name of the metadata that we wish to associate with this
                sensorgraph.
            value (object): The value we wish to store.
        """

        if name in self.metadata_database:
            raise ArgumentError("Attempted to set the same metadata value twice", name=name, old_value=self.metadata_database[name], new_value=value)

        self.metadata_database[name] = value

    def initialize_remaining_constants(self, value=0):
        """Ensure that all constant streams referenced in the sensor graph have a value.

        Constant streams that are automatically created by the compiler are initialized
        as part of the compilation process but it's possible that the user references
        other constant streams but never assigns them an explicit initial value.  This
        function will initialize them all to a default value (0 if not passed) and
        return the streams that were so initialized.

        Args:
            value (int): Optional value to use to initialize all uninitialized constants.
                Defaults to 0 if not passed.

        Returns:
            list(DataStream): A list of all of the constant streams that were not previously
                initialized and were initialized to the given value in this function.
        """

        remaining = []

        for node, _inputs, _outputs in self.iterate_bfs():
            streams = node.input_streams() + [node.stream]

            for stream in streams:
                if stream.stream_type is not DataStream.ConstantType:
                    continue

                if stream not in self.constant_database:
                    self.add_constant(stream, value)
                    remaining.append(stream)

        return remaining

    def load_constants(self):
        """Load all constants into their respective streams.

        All previous calls to add_constant stored a constant value that
        should be associated with virtual stream walkers.  This function
        actually calls push_stream in order to push all of the constant
        values to their walkers.
        """

        for stream, value in self.constant_database.items():
            self.sensor_log.push(stream, IOTileReading(stream.encode(), 0, value))

    def get_config(self, slot, config_id):
        """Get a config variable assignment previously set on this sensor graph.

        Args:
            slot (SlotIdentifier): The slot that we are setting this config variable
                on.
            config_id (int): The 16-bit config variable identifier.

        Returns:
            (str, str|int): Returns a tuple with the type of the config variable and
                the value that is being set.

        Raises:
            ArgumentError: If the config variable is not currently set on the specified
                slot.
        """

        if slot not in self.config_database:
            raise ArgumentError("No config variables have been set on specified slot", slot=slot)

        if config_id not in self.config_database[slot]:
            raise ArgumentError("Config variable has not been set on specified slot", slot=slot, config_id=config_id)

        return self.config_database[slot][config_id]

    def is_output(self, stream):
        """Check if a stream is a sensor graph output.

        Return:
            bool
        """

        for streamer in self.streamers:
            if streamer.selector.matches(stream):
                return True

        return False

    def get_tick(self, name):
        """Check the config variables to see if there is a configurable tick.

        Sensor Graph has a built-in 10 second tick that is sent every 10
        seconds to allow for triggering timed events.  There is a second
        'user' tick that is generated internally by the sensorgraph compiler
        and used for fast operations and finally there are several field
        configurable ticks that can be used for setting up configurable
        timers.

        This is done by setting a config variable on the controller with the
        desired tick interval, which is then interpreted by this function.

        The appropriate config_id to use is listed in `known_constants.py`

        Returns:
            int: 0 if the tick is disabled, otherwise the number of seconds
                between each tick
        """

        name_map = {
            'fast': config_fast_tick_secs,
            'user1': config_tick1_secs,
            'user2': config_tick2_secs
        }

        config = name_map.get(name)
        if config is None:
            raise ArgumentError("Unknown tick requested", name=name)

        slot = SlotIdentifier.FromString('controller')

        try:
            var = self.get_config(slot, config)
            return var[1]
        except ArgumentError:
            return 0

    def process_input(self, stream, value, rpc_executor):
        """Process an input through this sensor graph.

        The tick information in value should be correct and is transfered
        to all results produced by nodes acting on this tick.

        Args:
            stream (DataStream): The stream the input is part of
            value (IOTileReading): The value to process
            rpc_executor (RPCExecutor): An object capable of executing RPCs
                in case we need to do that.
        """

        self.sensor_log.push(stream, value)

        # FIXME: This should be specified in our device model
        if stream.important:
            associated_output = stream.associated_stream()
            self.sensor_log.push(associated_output, value)

        to_check = deque([x for x in self.roots])

        while len(to_check) > 0:
            node = to_check.popleft()
            if node.triggered():
                try:
                    results = node.process(rpc_executor, self.mark_streamer)
                    for result in results:
                        result.raw_time = value.raw_time
                        self.sensor_log.push(node.stream, result)
                except:
                    self._logger.exception("Unhandled exception in graph node processing function for node %s", str(node))

                # If we generated any outputs, notify our downstream nodes
                # so that they are also checked to see if they should run.
                if len(results) > 0:
                    to_check.extend(node.outputs)

    def mark_streamer(self, index):
        """Manually mark a streamer that should trigger.

        The next time check_streamers is called, the given streamer will be
        manually marked that it should trigger, which will cause it to trigger
        unless it has no data.

        Args:
            index (int): The index of the streamer that we should mark as
                manually triggered.

        Raises:
            ArgumentError: If the streamer index is invalid.
        """

        self._logger.debug("Marking streamer %d manually", index)
        if index >= len(self.streamers):
            raise ArgumentError("Invalid streamer index", index=index, num_streamers=len(self.streamers))

        self._manually_triggered_streamers.add(index)

    def check_streamers(self, blacklist=None):
        """Check if any streamers are ready to produce a report.

        You can limit what streamers are checked by passing a set-like
        object into blacklist.

        This method is the primary way to see when you should poll a given
        streamer for its next report.

        Note, this function is not idempotent.  If a streamer is marked as
        manual and it is triggered from a node rule inside the sensor_graph,
        that trigger will only last as long as the next call to
        check_streamers() so you need to explicitly build a report on all
        ready streamers before calling check_streamers again.

        Args:
            blacklist (set): Optional set of streamer indices that should
                not be checked right now.

        Returns:
            list of DataStreamer: A list of the ready streamers.
        """

        ready = []
        selected = set()

        for i, streamer in enumerate(self.streamers):
            if blacklist is not None and i in blacklist:
                continue

            if i in selected:
                continue

            marked = False
            if i in self._manually_triggered_streamers:
                marked = True
                self._manually_triggered_streamers.remove(i)

            if streamer.triggered(marked):
                self._logger.debug("Streamer %d triggered, manual=%s", i, marked)
                ready.append(streamer)
                selected.add(i)

                # Handle streamers triggered with another
                for j, streamer2 in enumerate(self.streamers[i:]):
                    if streamer2.with_other == i and j not in selected and streamer2.triggered(True):
                        self._logger.debug("Streamer %d triggered due to with-other on %d", j, i)
                        ready.append(streamer2)
                        selected.add(j)

        return ready

    def iterate_bfs(self):
        """Generator that yields node, [inputs], [outputs] in breadth first order.

        This generator will iterate over all nodes in the sensor graph, yielding
        a 3 tuple for each node with a list of all of the nodes connected to its
        inputs and all of the nodes connected to its output.

        Returns:
            (SGNode, list(SGNode), list(SGNode)): A tuple for each node in the graph
        """

        working_set = deque(self.roots)
        seen = []

        while len(working_set) > 0:
            curr = working_set.popleft()

            # Now build input and output node lists for this node
            inputs = []
            for walker, _ in curr.inputs:
                for other in seen:
                    if walker.matches(other.stream) and other not in inputs:
                        inputs.append(other)

            outputs = [x for x in curr.outputs]
            yield curr, inputs, outputs

            working_set.extend(curr.outputs)
            seen.append(curr)

    def sort_nodes(self):
        """Topologically sort all of our nodes.

        Topologically sorting our nodes makes nodes that are inputs to other
        nodes come first in the list of nodes.  This is important to do before
        programming a sensorgraph into an embedded device whose engine assumes
        a topologically sorted graph.

        The sorting is done in place on self.nodes
        """

        node_map = {id(node): i for i, node in enumerate(self.nodes)}
        node_deps = {}

        for node, inputs, _outputs in self.iterate_bfs():
            node_index = node_map[id(node)]

            deps = {node_map[id(x)] for x in inputs}
            node_deps[node_index] = deps

        # Now that we have our dependency tree properly built, topologically
        # sort the nodes and reorder them.
        node_order = toposort_flatten(node_deps)
        self.nodes = [self.nodes[x] for x in node_order]

        #Check root nodes all topographically sorted to the beginning
        for root in self.roots:
            if root not in self.nodes[0:len(self.roots)]:
                raise NodeConnectionError("Inputs not sorted in the beginning", node=str(root), node_position=self.nodes.index(root))

    @classmethod
    def find_processing_function(cls, name):
        """Find a processing function by name.

        This function searches through installed processing functions
        using pkg_resources.

        Args:
            name (str): The name of the function we're looking for

        Returns:
            callable: The processing function
        """

        for entry in iter_entry_points(u'iotile.sg_processor', name):
            return entry.load()

    def dump_nodes(self):
        """Dump all of the nodes in this sensor graph as a list of strings."""

        return [str(x) for x in self.nodes]

    def dump_streamers(self):
        """Dump all of the streamers in this sensor graph as a list of strings."""

        return [str(streamer) for streamer in self.streamers]
