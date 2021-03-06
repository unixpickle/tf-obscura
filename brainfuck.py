"""
A Brainfuck interpreter in the TF graph.

See: https://en.wikipedia.org/wiki/Brainfuck.
"""

from functools import partial

import tensorflow as tf

def show_example():
    """
    Run a quick and dirty program.
    """
    source_ph = tf.placeholder(tf.string)
    input_ph = tf.placeholder(tf.string)
    output = run_program(source_ph, input_ph)
    with tf.Session() as sess:
        source_code = ('++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]' +
                       '>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.' +
                       ',[.,]')
        input_buffer = ' (said the BF program)'
        print('output:', sess.run(output, feed_dict={source_ph: source_code,
                                                     input_ph: input_buffer}))

def run_program(code_str, input_str, memory_size=4096):
    """
    Run a program and get the result.

    Args:
      code_str: a 0-D string Tensor.
      input_str: a 0-D input Tensor.

    Returns:
      output: a 0-D string Tensor of the output.
    """
    code = tf.decode_raw(code_str, tf.uint8)
    # pylint: disable=E1120
    res = tf.while_loop(lambda *args: State(*args).code_ptr < tf.shape(code)[0],
                        lambda *args: step_program(code, State(*args)),
                        State.init_state(input_str, memory_size).as_tuple())
    return State(*res).output_str

def step_program(code, state):
    """
    Run one instruction of the program.

    Args:
      code: a 1-D uint8 Tensor of code symbols.
      state: the current state.

    Returns:
      The new state tuple.
    """
    inst = code[state.code_ptr]
    conds = [('<', '>'), ('+', '-'), ('['), (']'), (','), ('.')]
    raw_funcs = [adjust_mem_pointer, adjust_mem, partial(loop_open, code),
                 partial(loop_close, code), read_input, write_output]
    preds = [instruction_equals(inst, *cond) for cond in conds]
    funcs = [lambda f=func: f(inst, state).as_tuple() for func in raw_funcs]
    return tf.case(list(zip(preds, funcs)),
                   default=lambda: state.next().as_tuple())

def instruction_equals(inst, *options):
    """
    Produce a 0-D boolean Tensor which is true if the
    instruction Tensor is one of the options.
    """
    res = tf.equal(inst, ord(options[0]))
    for opt in options[1:]:
        res = tf.logical_or(res, tf.equal(inst, ord(opt)))
    return res

def adjust_mem_pointer(inst, state):
    """
    Perform a '<' or '>' instruction.
    """
    offset = tf.cond(instruction_equals(inst, '<'),
                     true_fn=partial(tf.constant, -1, dtype=tf.int32),
                     false_fn=partial(tf.constant, 1, dtype=tf.int32))
    return state.add_mem_ptr(offset).next()

def adjust_mem(inst, state):
    """
    Perform a '-' or '+' instruction.
    """
    offset = tf.cond(instruction_equals(inst, '-'),
                     true_fn=partial(tf.constant, 0xff, dtype=tf.uint8),
                     false_fn=partial(tf.constant, 1, dtype=tf.uint8))
    return state.add_mem(offset).next()

def loop_open(code, _, state):
    """
    Perform a '[' instruction.
    """
    return state.jump(tf.cond(tf.equal(state.read_mem(), 0),
                              true_fn=lambda: matching_bracket(code, state.code_ptr, 1)+1,
                              false_fn=lambda: state.code_ptr+1))

def loop_close(code, _, state):
    """
    Perform a ']' instruction.
    """
    return state.jump(tf.cond(tf.not_equal(state.read_mem(), 0),
                              true_fn=lambda: matching_bracket(code, state.code_ptr, -1)+1,
                              false_fn=lambda: state.code_ptr+1))

def read_input(_, state):
    """
    Perform a ',' instruction.
    """
    in_byte = tf.cond(state.input_ptr < tf.shape(state.inputs)[0],
                      true_fn=lambda: state.inputs[state.input_ptr],
                      false_fn=partial(tf.constant, 0, dtype=tf.uint8))
    return state.write_mem(in_byte).add_input_ptr(1).next()

def write_output(_, state):
    """
    Perform a '.' instruction.
    """
    return state.write_output(state.read_mem()).next()

def matching_bracket(code, code_ptr, direction):
    """
    Find the code pointer of a matching bracket.

    Args:
      code: the code buffer.
      code_ptr: the current code pointer.
      direction: 1 for finding a ']', or -1 for '['.
    """
    counter = tf.constant(1, dtype=tf.int32)
    # pylint: disable=E0602
    return tf.while_loop(lambda c, _: c > 0,
                         lambda c, p: (tf.case([(tf.equal(code[p + direction], ord('[')),
                                                 lambda: c + direction),
                                                (tf.equal(code[p + direction], ord(']')),
                                                 lambda: c - direction)],
                                               default=lambda: c),
                                       p + direction),
                         (counter, code_ptr))[1]

class State:
    """
    The state of a Brainfuck interpreter.

    The state is immutable.
    """
    # pylint: disable=R0913
    def __init__(self, code_ptr, mem_ptr, input_ptr, mem, inputs, output_str):
        self.code_ptr = code_ptr
        self.mem_ptr = mem_ptr
        self.input_ptr = input_ptr
        self.mem = mem
        self.inputs = inputs
        self.output_str = output_str

    def as_tuple(self):
        """
        Convert the state to a tuple.

        The tuple can be expanded for __init__.
        """
        return (self.code_ptr, self.mem_ptr, self.input_ptr,
                self.mem, self.inputs, self.output_str)

    def next(self):
        """
        Advance the code pointer.
        """
        return self.jump(self.code_ptr + 1)

    def jump(self, addr):
        """
        Set the code pointer.
        """
        res = self._copy()
        res.code_ptr = addr
        return res

    def add_mem_ptr(self, offset):
        """
        Add a value to the memory pointer.
        """
        res = self._copy()
        res.mem_ptr = res.mem_ptr + offset
        return res

    def add_input_ptr(self, offset):
        """
        Add a value to the input pointer.
        """
        res = self._copy()
        res.input_ptr = res.input_ptr + offset
        return res

    def read_mem(self):
        """
        Get the current memory cell value.
        """
        return self.mem[self.mem_ptr]

    def write_mem(self, value):
        """
        Set the current memory cell value.
        """
        res = self._copy()
        mem_size = tf.shape(res.mem)[0]
        repeated_value = tf.tile(tf.stack([value]), (mem_size,))
        res.mem = tf.where(tf.equal(tf.range(mem_size), self.mem_ptr),
                           repeated_value,
                           res.mem)
        return res

    def add_mem(self, value):
        """
        Add a value to the current memory cell.
        """
        return self.write_mem(self.read_mem() + value)

    def write_output(self, value):
        """
        Add a value to the output string.
        """
        output_table = tf.constant([chr(i) for i in range(0x100)])
        char_str = output_table[tf.cast(value, tf.int32)]
        res = self._copy()
        res.output_str = tf.string_join((res.output_str, char_str))
        return res

    @staticmethod
    def init_state(input_str, memory_size):
        """
        Create an initial interpreter state.
        """
        return State(tf.constant(0, dtype=tf.int32),
                     tf.constant(memory_size//2, dtype=tf.int32),
                     tf.constant(0, dtype=tf.int32),
                     tf.constant([0]*memory_size, dtype=tf.uint8),
                     tf.decode_raw(input_str, tf.uint8),
                     tf.constant(''))

    def _copy(self):
        """
        Create a shallow copy.
        """
        return State(*self.as_tuple())

if __name__ == '__main__':
    show_example()
