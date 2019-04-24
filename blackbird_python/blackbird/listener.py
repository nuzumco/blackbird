# Copyright 2019 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# pylint: disable=too-many-return-statements,too-many-branches,too-many-instance-attributes
"""
Python Blackbird Listener
=========================

**Module name:** `blackbird.listener`

.. currentmodule:: blackbird.listener

This module contains the main Blackbird listener,
:class:`~.BlackbirdListener`. It inherits from the class :class:`.blackbirdListener`
contained in the file ``blackbirdListener.py``, which is autogenerated
by ANTLR4.

In addition, a small utility function, which automates the parsing of a
Blackbird script and returns the completed listener, is included.

Summary
-------

.. autosummary::
    PYTHON_TYPES
    NUMPY_TYPES
    RegRefTransform
    BlackbirdListener
    parse_blackbird

Code details
~~~~~~~~~~~~
"""
import antlr4

import numpy as np
import sympy as sym

from .blackbirdLexer import blackbirdLexer
from .blackbirdParser import blackbirdParser
from .blackbirdListener import blackbirdListener

from .error import BlackbirdErrorListener, BlackbirdSyntaxError
from .auxiliary import _expression, _get_arguments, _literal, _VAR


PYTHON_TYPES = {
    "array": np.ndarray,
    "float": float,
    "complex": complex,
    "int": int,
    "str": str,
    "bool": bool,
}
"""dict[str->type]: Mapping from the allowed Blackbird types
to the equivalent Python/NumPy types."""


NUMPY_TYPES = {
    "float": np.float64,
    "complex": np.complex128,
    "int": np.int64,
    "str": np.str,
    "bool": np.bool,
}
"""dict[str->type]: Mapping from the allowed Blackbird array types
to the equivalent NumPy data types."""


class RegRefTransform:
    """Class to represent a classical register transform.

    Args:
        expr (sympy.Expr): a SymPy expression representing the RegRef transform
    """

    def __init__(self, expr):
        """After initialization, the RegRefTransform has three attributes
        which may be inspected to translate the Blackbird program to a
        simulator or quantum hardware:

        * :attr:`func`
        * :attr:`regrefs`
        * :attr:`func_str`
        """
        regref_symbols = list(expr.free_symbols)
        # get the Python function represented by the regref transform
        self.func = sym.lambdify(regref_symbols, expr)
        """function: Scalar function that takes one or more values corresponding
        to measurement results, and outputs a single numeric value."""

        # get the regrefs involved
        self.regrefs = [int(str(i)[1:]) for i in regref_symbols]
        """list[int]: List of integers corresponding to the modes that are measured
        and act as inputs to :attr:`func`. Note that the order of this list corresponds
        to the order that the measured mode results should be passed to the function."""

        self.func_str = str(expr)
        """str: String representation of the RegRefTransform function."""

    def __str__(self):
        """Print formatting"""
        return self.func_str

    __repr__ = __str__


class BlackbirdListener(blackbirdListener):
    """Listener to run a Blackbird program and extract the program queue and target information."""

    def __init__(self):
        """On initialization, the Blackbird listener creates the following empty attributes:

        * :attr:`name = "" <name>`
        * :attr:`version = None <version>`
        * :attr:`var = {} <var>`
        * :attr:`target = None <target>`
        * :attr:`queue = [] <queue>`
        """
        self.name = ""
        """str: Name of the Blackbird program"""

        self.version = None
        """float: Version of the Blackbird parser the script targets"""

        self.active_modes = set()
        """set[int]: A set of non-negative integers specifying the modes the program manipulates."""

        self.var = {}
        """dict[str->[int, float, complex, str, bool, numpy.ndarray]]: Mapping from the
        variable names in the Blackbird script to their declared values."""

        self.target = None
        """dict[str->[str, dict]]: Contains information regarding the target device of the quantum
        program (i.e., the target device the Blackbird script is compiled for).

        Important keys include:

        * ``'name'`` (str): the name of the device the Blackbird script requests to be run on
        * ``'options'`` (dict): a dictionary of keyword arguments for the target device
        """

        self.queue = []
        """list[dict]: List of operations to apply to the device, in temporal order.
        Each operation is contained as a dictionary, with the following keys:

        * ``'op'`` (str): the name of the operation
        * ``'args'`` (list): a list of positional arguments for the operation
        * ``'kwargs'`` (dict): a dictionary of keyword arguments for the operation
        * ``'modes'`` (list[int]): modes the operation applies to

        Note that, depending on the operation, both ``'args'`` and ``'kwargs'``
        might be empty.
        """

    def exitDeclarename(self, ctx: blackbirdParser.DeclarenameContext):
        """Run after exiting program name metadata.

        Args:
            ctx: DeclarenameContext
        """
        self.name = ctx.programname().getText()

    def exitVersion(self, ctx: blackbirdParser.VersionContext):
        """Run after exiting version metadata.

        Args:
            ctx: VersionContext
        """
        self.version = ctx.versionnumber().getText()

    def exitTarget(self, ctx: blackbirdParser.TargetContext):
        """Run after exiting target metadata.

        Args:
            ctx: TargetContext
        """
        self.target = {"name": ctx.device().getText()}

        args = []
        kwargs = {}

        if ctx.arguments():
            args, kwargs = _get_arguments(ctx.arguments())

        self.target["options"] = kwargs

    def exitExpressionvar(self, ctx: blackbirdParser.ExpressionvarContext):
        """Run after exiting an expression variable.

        Args:
            ctx: variable context
        """
        name = ctx.name().getText()
        vartype = ctx.vartype().getText()

        if ctx.name().invalid():
            child = ctx.name().invalid()
            line = child.start.line
            col = child.start.column

            if child.REGREF():
                raise BlackbirdSyntaxError(
                    "Blackbird SyntaxError (line {}:{}): Variable name '{}' is reserved for register references".format(
                        line, col, name
                    )
                )
            if child.reserved():
                raise BlackbirdSyntaxError(
                    "Blackbird SyntaxError (line {}:{}): Variable name '{}' is a reserved Blackbird keyword".format(
                        line, col, name
                    )
                )

        if ctx.expression():
            value = _expression(ctx.expression())
        elif ctx.nonnumeric():
            value = _literal(ctx.nonnumeric())

        try:
            # assume all variables are scalar
            final_value = PYTHON_TYPES[vartype](value)
        except:
            try:
                # maybe one of the variables was a NumPy array?
                final_value = NUMPY_TYPES[vartype](value)
            except:
                # nope
                raise TypeError(
                    "Var {} = {} is not of declared type {}".format(name, value, vartype)
                ) from None

        _VAR[name] = final_value

    def exitArrayvar(self, ctx: blackbirdParser.ArrayvarContext):
        """Run after exiting an array variable.

        Args:
            ctx: array variable context
        """
        name = ctx.name().getText()
        vartype = ctx.vartype().getText()

        if ctx.name().invalid():
            child = ctx.name().invalid()
            line = child.start.line
            col = child.start.column

            if child.REGREF():
                raise BlackbirdSyntaxError(
                    "Blackbird SyntaxError (line {}:{}): Variable name '{}' is reserved for register references".format(
                        line, col, name
                    )
                )
            if child.reserved():
                raise BlackbirdSyntaxError(
                    "Blackbird SyntaxError (line {}:{}): Variable name '{}' is a reserved Blackbird keyword".format(
                        line, col, name
                    )
                )

        shape = None
        if ctx.shape():
            shape = tuple([int(i) for i in ctx.shape().getText().split(",")])

        value = []
        # loop through all children of the 'arrayval' branch
        for i in ctx.arrayval().getChildren():
            # Check if the child is an array row (this is to
            # avoid the '\n' row delimiter)
            if isinstance(i, blackbirdParser.ArrayrowContext):
                value.append([])
                for j in i.getChildren():
                    # Check if the child is not the column delimiter ','
                    if j.getText() != ",":
                        value[-1].append(_expression(j))

        try:
            final_value = np.array(value, dtype=NUMPY_TYPES[vartype])
        except:
            line = ctx.start.line
            col = ctx.start.column
            raise BlackbirdSyntaxError(
                "Blackbird SyntaxError (line {}:{}): Array var {} is not of declared type {}".format(
                    line, col, name, vartype
                )
            )

        if shape is not None:
            actual_shape = final_value.shape
            if actual_shape != shape:
                line = ctx.start.line
                col = ctx.start.column
                raise BlackbirdSyntaxError(
                    "Blackbird SyntaxError (line {}:{}): Array var {} has declared shape {} "
                    "but actual shape {}".format(line, col, name, shape, actual_shape)
                )

        _VAR[name] = final_value

    def exitStatement(self, ctx: blackbirdParser.StatementContext):
        """Run after exiting a quantum statement.

        Args:
            ctx: statement context
        """
        if ctx.operation():
            op = ctx.operation().getText()
        elif ctx.measure():
            op = ctx.measure().getText()

        modes = [int(i) for i in ctx.modes().getText().split(",")]
        self.active_modes |= set(modes)

        if ctx.arguments():
            op_args, op_kwargs = _get_arguments(ctx.arguments())

            # convert any sympy expressions into regref transforms
            op_args = [RegRefTransform(i) if isinstance(i, sym.Expr) else i for i in op_args]

            self.queue.append({"op": op, "args": op_args, "kwargs": op_kwargs, "modes": modes})
        else:
            self.queue.append({"op": op, "modes": modes})

    def exitProgram(self, ctx: blackbirdParser.ProgramContext):
        """Run after exiting the program block.

        Args:
            ctx: program context
        """
        self.var.update(_VAR)
        _VAR.clear()


def parse_blackbird(file, listener=BlackbirdListener):
    """Parse a blackbird program.

    Args:
        file (str): location of the .xbb blackbird file to run
        Listener (BlackbirdListener): an Blackbird listener to use to walk the AST.
            By default, the basic :class:`~.BlackbirdListener` defined above
            is used.

    Returns:
        BlackbirdListener: returns the Blackbird listener instance after
        parsing the abstract syntax tree
    """
    data = antlr4.FileStream(file)
    lexer = blackbirdLexer(data)
    stream = antlr4.CommonTokenStream(lexer)

    parser = blackbirdParser(stream)
    parser.removeErrorListeners()
    parser.addErrorListener(BlackbirdErrorListener())
    tree = parser.start()

    blackbird = listener()
    walker = antlr4.ParseTreeWalker()
    walker.walk(blackbird, tree)

    return blackbird
