# coding=utf-8
# Copyright 2018 The TF-Agents Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A tensorflow table stored in tf.Variables.

The row is the index or location at which the value is saved, and the value is
a nest of Tensors.

This class is not threadsafe.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

nest = tf.contrib.framework.nest


class Table(tf.contrib.checkpoint.Checkpointable):
  """A table that can store Tensors or nested Tensors."""

  def __init__(self, tensor_spec, capacity, scope='Table'):
    """Creates a table.

    Args:
      tensor_spec: A nest of TensorSpec representing each value that can be
        stored in the table.
      capacity: Maximum number of values the table can store.
      scope: Variable scope for the Table.
    Raises:
      ValueError: If the names in tensor_spec are empty or not unique.
    """
    self._tensor_spec = tensor_spec
    self._capacity = capacity
    # For tracking slots as a checkpointable dependencies.
    self._tracker = tf.contrib.checkpoint.UniqueNameTracker()

    def _create_unique_slot_name(spec):
      return tf.get_default_graph().unique_name(spec.name or 'slot')
    self._slots = nest.map_structure(_create_unique_slot_name,
                                     self._tensor_spec)

    def _create_storage(spec, slot_name):
      """Create storage for a slot, track it."""
      new_storage = tf.get_variable(
          name=slot_name,
          shape=[self._capacity] + spec.shape.as_list(),
          dtype=spec.dtype,
          initializer=tf.zeros_initializer,
          trainable=False,
          use_resource=True,
      )
      self._tracker.track(new_storage, slot_name)
      return new_storage

    with tf.variable_scope(scope):
      self._storage = nest.map_structure(_create_storage, self._tensor_spec,
                                         self._slots)

    self._slot2storage_map = dict(
        zip(nest.flatten(self._slots), nest.flatten(self._storage)))

  @property
  def slots(self):
    return self._slots

  def variables(self):
    return nest.flatten(self._storage)

  def read(self, rows, slots=None):
    """Returns values for the given rows.

    Args:
      rows: A scalar/list/tensor of location(s) to read values from. If rows is
        a scalar, a single value is returned without a batch dimension. If rows
        is a list of integers or a rank-1 int Tensor a batch of values will be
        returned with each Tensor having an extra first dimension equal to the
        length of rows.
      slots: Optional list/tuple/nest of slots to read from. If None, all
        tensors at the given rows are retrieved and the return value has the
        same structure as the tensor_spec. Otherwise, only tensors with names
        matching the slots are retrieved, and the return value has the same
        structure as slots.

    Returns:
      Values at given rows.
    """
    slots = slots or self._slots
    flattened_slots = nest.flatten(slots)
    values = [
        self._slot2storage_map[slot].sparse_read(rows)
        for slot in flattened_slots
    ]
    return nest.pack_sequence_as(slots, values)

  def write(self, rows, values, slots=None):
    """Returns ops for writing values at the given rows.

    Args:
      rows: A scalar/list/tensor of location(s) to write values at.
      values: A nest of Tensors to write. If rows has more than one element,
        values can have an extra first dimension representing the batch size.
        Values must have the same structure as the tensor_spec of this class
        if `slots` is None, otherwise it must have the same structure as
        `slots`.
      slots: Optional list/tuple/nest of slots to write. If None, all tensors
        in the table are updated. Otherwise, only tensors with names matching
        the slots are updated.

    Returns:
      Ops for writing values at rows.
    """
    slots = slots or self._slots
    flattened_slots = nest.flatten(slots)
    flattened_values = nest.flatten(values)
    write_ops = [
        tf.scatter_update(self._slot2storage_map[slot], rows, value)
        for (slot, value) in zip(flattened_slots, flattened_values)
    ]
    return tf.group(*write_ops)