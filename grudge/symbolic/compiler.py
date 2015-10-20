"""Compiler to turn operator expression tree into (imperative) bytecode."""

from __future__ import division, absolute_import, print_function

__copyright__ = "Copyright (C) 2008-15 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


import six
from six.moves import zip, reduce
from pytools import Record, memoize_method, memoize
from grudge import sym
import grudge.symbolic.mappers as mappers


# {{{ instructions

class Instruction(Record):
    __slots__ = []
    priority = 0

    def get_assignees(self):
        raise NotImplementedError("no get_assignees in %s" % self.__class__)

    def get_dependencies(self):
        raise NotImplementedError("no get_dependencies in %s" % self.__class__)

    def __str__(self):
        raise NotImplementedError

    def get_execution_method(self, exec_mapper):
        raise NotImplementedError

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return not self.__eq__(other)


@memoize
def _make_dep_mapper(include_subscripts):
    return mappers.DependencyMapper(
            include_operator_bindings=False,
            include_subscripts=include_subscripts,
            include_calls="descend_args")


class Assign(Instruction):
    """
    .. attribute:: names
    .. attribute:: exprs
    .. attribute:: do_not_return

        a list of bools indicating whether the corresponding entry in names and
        exprs describes an expression that is not needed beyond this assignment

    .. attribute:: priority
    .. attribute:: is_scalar_valued
    """

    comment = ""

    def __init__(self, names, exprs, **kwargs):
        Instruction.__init__(self, names=names, exprs=exprs, **kwargs)

        if not hasattr(self, "do_not_return"):
            self.do_not_return = [False] * len(names)

    @memoize_method
    def flop_count(self):
        return sum(mappers.FlopCounter()(expr) for expr in self.exprs)

    def get_assignees(self):
        return set(self.names)

    @memoize_method
    def get_dependencies(self, each_vector=False):
        dep_mapper = _make_dep_mapper(include_subscripts=False)

        from operator import or_
        deps = reduce(
                or_, (dep_mapper(expr)
                for expr in self.exprs))

        from pymbolic.primitives import Variable
        deps -= set(Variable(name) for name in self.names)

        if not each_vector:
            self._dependencies = deps

        return deps

    def __str__(self):
        comment = self.comment
        if len(self.names) == 1:
            if comment:
                comment = "/* %s */ " % comment

            return "%s <- %s%s" % (self.names[0], comment, self.exprs[0])
        else:
            if comment:
                comment = " /* %s */" % comment

            lines = []
            lines.append("{" + comment)
            for n, e, dnr in zip(self.names, self.exprs, self.do_not_return):
                if dnr:
                    dnr_indicator = "-#"
                else:
                    dnr_indicator = ""

                lines.append("  %s <%s- %s" % (n, dnr_indicator, e))
            lines.append("}")
            return "\n".join(lines)

    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_assign


class FluxBatchAssign(Instruction):
    """
    .. attribute:: names
    .. attribute:: expressions

        A list of :class:`grudge.symbolic.primitives.OperatorBinding`
        instances bound to flux operators.

        .. note ::

            All operators in :attr:`expressions` are guaranteed to
            yield the same operator from
            :meth:`grudge.symbolic.operators.FluxOperatorBase.repr_op`.

    .. attribute:: repr_op

        The *repr_op* on which all operators agree.

    .. attribute:: quadrature_tag
    """

    def get_assignees(self):
        return set(self.names)

    @memoize_method
    def get_dependencies(self):
        deps = set()
        for wdflux in self.expressions:
            deps |= set(wdflux.interior_deps)
            deps |= set(wdflux.boundary_deps)

        dep_mapper = _make_dep_mapper(include_subscripts=False)

        from pytools import flatten
        return set(flatten(dep_mapper(dep) for dep in deps))

    def __str__(self):
        from grudge.symbolic.flux.mappers import PrettyFluxStringifyMapper as PFSM
        flux_strifier = PFSM()
        op_strifier = mappers.StringifyMapper(flux_stringify_mapper=flux_strifier)

        from pymbolic.mapper.stringifier import PREC_NONE

        lines = []
        lines.append("{ /* %s */" % self.repr_op)

        lines_expr = []
        for n, f in zip(self.names, self.expressions):
            lines_expr.append("  %s <- %s" % (n, op_strifier(f, PREC_NONE)))

        for n, str_f in getattr(flux_strifier, "cse_name_list", []):
            lines.append("  (flux-local) %s <- %s" % (n, str_f))

        lines.extend(lines_expr)
        lines.append("}")
        return "\n".join(lines)

    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_flux_batch_assign


class DiffBatchAssign(Instruction):
    """
    :ivar names:
    :ivar operators:

        .. note ::

            All operators here are guaranteed to satisfy
            :meth:`grudge.symbolic.operators.DiffOperatorBase.
            equal_except_for_axis`.

    :ivar field:
    """

    def get_assignees(self):
        return set(self.names)

    @memoize_method
    def get_dependencies(self):
        return _make_dep_mapper(include_subscripts=False)(self.field)

    def __str__(self):
        lines = []

        if len(self.names) > 1:
            lines.append("{")
            for n, d in zip(self.names, self.operators):
                lines.append("  %s <- %s(%s)" % (n, d, self.field))
            lines.append("}")
        else:
            for n, d in zip(self.names, self.operators):
                lines.append("%s <- %s(%s)" % (n, d, self.field))

        return "\n".join(lines)

    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_diff_batch_assign


class QuadratureDiffBatchAssign(DiffBatchAssign):
    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_quad_diff_batch_assign


class FluxExchangeBatchAssign(Instruction):
    """
    .. attribute:: names
    .. attribute:: indices_and_ranks
    .. attribute:: rank_to_index_and_name
    .. attribute:: arg_fields
    """

    priority = 1

    def __init__(self, names, indices_and_ranks, arg_fields):
        rank_to_index_and_name = {}
        for name, (index, rank) in zip(
                names, indices_and_ranks):
            rank_to_index_and_name.setdefault(rank, []).append(
                (index, name))

        Instruction.__init__(self,
                names=names,
                indices_and_ranks=indices_and_ranks,
                rank_to_index_and_name=rank_to_index_and_name,
                arg_fields=arg_fields)

    def get_assignees(self):
        return set(self.names)

    @memoize_method
    def get_dependencies(self):
        dep_mapper = _make_dep_mapper()
        result = set()
        for fld in self.arg_fields:
            result |= dep_mapper(fld)
        return result

    def __str__(self):
        lines = []

        lines.append("{")
        for n, (index, rank) in zip(self.names, self.indices_and_ranks):
            lines.append("  %s <- receive index %s from rank %d [%s]" % (
                n, index, rank, self.arg_fields))
        lines.append("}")

        return "\n".join(lines)

    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_flux_exchange_batch_assign


class VectorExprAssign(Assign):
    """
    .. attribute:: compiled
    """

    def get_execution_method(self, exec_mapper):
        return exec_mapper.exec_vector_expr_assign

    comment = "compiled"

    @memoize_method
    def compiled(self, exec_mapper):
        discr = exec_mapper.discr

        from grudge.backends.vector_expr import \
                VectorExpressionInfo, simple_result_dtype_getter
        from grudge.backends.cuda.vector_expr import CompiledVectorExpression
        return CompiledVectorExpression(
                [VectorExpressionInfo(
                    name=name,
                    expr=expr,
                    do_not_return=dnr)
                    for name, expr, dnr in zip(
                        self.names, self.exprs, self.do_not_return)],
                result_dtype_getter=simple_result_dtype_getter,
                allocator=discr.pool.allocate)

# }}}


# {{{ graphviz/dot dataflow graph drawing

def dot_dataflow_graph(code, max_node_label_length=30,
        label_wrap_width=50):
    origins = {}
    node_names = {}

    result = [
            "initial [label=\"initial\"]"
            "result [label=\"result\"]"]

    for num, insn in enumerate(code.instructions):
        node_name = "node%d" % num
        node_names[insn] = node_name
        node_label = str(insn)

        if max_node_label_length is not None:
            node_label = node_label[:max_node_label_length]

        if label_wrap_width is not None:
            from pytools import word_wrap
            node_label = word_wrap(node_label, label_wrap_width,
                    wrap_using="\n      ")

        node_label = node_label.replace("\n", "\\l") + "\\l"

        result.append("%s [ label=\"p%d: %s\" shape=box ];" % (
            node_name, insn.priority, node_label))

        for assignee in insn.get_assignees():
            origins[assignee] = node_name

    def get_orig_node(expr):
        from pymbolic.primitives import Variable
        if isinstance(expr, Variable):
            return origins.get(expr.name, "initial")
        else:
            return "initial"

    def gen_expr_arrow(expr, target_node):
        result.append("%s -> %s [label=\"%s\"];"
                % (get_orig_node(expr), target_node, expr))

    for insn in code.instructions:
        for dep in insn.get_dependencies():
            gen_expr_arrow(dep, node_names[insn])

    from grudge.tools import is_obj_array

    if is_obj_array(code.result):
        for subexp in code.result:
            gen_expr_arrow(subexp, "result")
    else:
        gen_expr_arrow(code.result, "result")

    return "digraph dataflow {\n%s\n}\n" % "\n".join(result)

# }}}


# {{{ code representation

class Code(object):
    def __init__(self, instructions, result):
        self.instructions = instructions
        self.result = result
        self.last_schedule = None
        self.static_schedule_attempts = 5

    def dump_dataflow_graph(self):
        from grudge.tools import open_unique_debug_file

        open_unique_debug_file("dataflow", ".dot")\
                .write(dot_dataflow_graph(self, max_node_label_length=None))

    def __str__(self):
        lines = []
        for insn in self.instructions:
            lines.extend(str(insn).split("\n"))
        lines.append("RESULT: " + str(self.result))

        return "\n".join(lines)

    # {{{ dynamic scheduler (generates static schedules by self-observation)

    class NoInstructionAvailable(Exception):
        pass

    @memoize_method
    def get_next_step(self, available_names, done_insns):
        from pytools import all, argmax2
        available_insns = [
                (insn, insn.priority) for insn in self.instructions
                if insn not in done_insns
                and all(dep.name in available_names
                    for dep in insn.get_dependencies())]

        if not available_insns:
            raise self.NoInstructionAvailable

        from pytools import flatten
        discardable_vars = set(available_names) - set(flatten(
            [dep.name for dep in insn.get_dependencies()]
            for insn in self.instructions
            if insn not in done_insns))

        # {{{ make sure results do not get discarded

        from pytools.obj_array import with_object_array_or_scalar

        dm = mappers.DependencyMapper(composite_leaves=False)

        def remove_result_variable(result_expr):
            # The extra dependency mapper run is necessary
            # because, for instance, subscripts can make it
            # into the result expression, which then does
            # not consist of just variables.

            for var in dm(result_expr):
                from pymbolic.primitives import Variable
                assert isinstance(var, Variable)
                discardable_vars.discard(var.name)

        with_object_array_or_scalar(remove_result_variable, self.result)

        # }}}

        return argmax2(available_insns), discardable_vars

    def execute_dynamic(self, exec_mapper, pre_assign_check=None):
        """Execute the instruction stream, make all scheduling decisions
        dynamically. Record the schedule in *self.last_schedule*.
        """
        schedule = []

        context = exec_mapper.context

        next_future_id = 0
        futures = []
        done_insns = set()

        force_future = False

        while True:
            insn = None
            discardable_vars = []

            # check futures for completion

            i = 0
            while i < len(futures):
                future = futures[i]
                if force_future or future.is_ready():
                    futures.pop(i)

                    insn = self.EvaluateFuture(future.id)

                    assignments, new_futures = future()
                    force_future = False
                    break
                else:
                    i += 1

                del future

            # if no future got processed, pick the next insn
            if insn is None:
                try:
                    insn, discardable_vars = self.get_next_step(
                            frozenset(list(context.keys())),
                            frozenset(done_insns))

                except self.NoInstructionAvailable:
                    if futures:
                        # no insn ready: we need a future to complete to continue
                        force_future = True
                    else:
                        # no futures, no available instructions: we're done
                        break
                else:
                    for name in discardable_vars:
                        del context[name]

                    done_insns.add(insn)
                    assignments, new_futures = \
                            insn.get_execution_method(exec_mapper)(insn)

            if insn is not None:
                for target, value in assignments:
                    if pre_assign_check is not None:
                        pre_assign_check(target, value)

                    context[target] = value

                futures.extend(new_futures)

                schedule.append((discardable_vars, insn, len(new_futures)))

                for future in new_futures:
                    future.id = next_future_id
                    next_future_id += 1

        if len(done_insns) < len(self.instructions):
            print("Unreachable instructions:")
            for insn in set(self.instructions) - done_insns:
                print("    ", insn)

            raise RuntimeError("not all instructions are reachable"
                    "--did you forget to pass a value for a placeholder?")

        if self.static_schedule_attempts:
            self.last_schedule = schedule

        from pytools.obj_array import with_object_array_or_scalar
        return with_object_array_or_scalar(exec_mapper, self.result)

    # }}}

    # {{{ static schedule execution
    class EvaluateFuture(object):
        """A fake 'instruction' that represents evaluation of a future."""
        def __init__(self, future_id):
            self.future_id = future_id

    def execute(self, exec_mapper, pre_assign_check=None):
        """If we have a saved, static schedule for this instruction stream,
        execute it. Otherwise, punt to the dynamic scheduler below.
        """

        if self.last_schedule is None:
            return self.execute_dynamic(exec_mapper, pre_assign_check)

        context = exec_mapper.context
        id_to_future = {}
        next_future_id = 0

        schedule_is_delay_free = True

        for discardable_vars, insn, new_future_count in self.last_schedule:
            for name in discardable_vars:
                del context[name]

            if isinstance(insn, self.EvaluateFuture):
                future = id_to_future.pop(insn.future_id)
                if not future.is_ready():
                    schedule_is_delay_free = False
                assignments, new_futures = future()
                del future
            else:
                assignments, new_futures = \
                        insn.get_execution_method(exec_mapper)(insn)

            for target, value in assignments:
                if pre_assign_check is not None:
                    pre_assign_check(target, value)

                context[target] = value

            if len(new_futures) != new_future_count:
                raise RuntimeError("static schedule got an unexpected number "
                        "of futures")

            for future in new_futures:
                id_to_future[next_future_id] = future
                next_future_id += 1

        if not schedule_is_delay_free:
            self.last_schedule = None
            self.static_schedule_attempts -= 1

        from pytools.obj_array import with_object_array_or_scalar
        return with_object_array_or_scalar(exec_mapper, self.result)

    # }}}

# }}}


# {{{ compiler

class OperatorCompiler(mappers.IdentityMapper):
    class FluxRecord(Record):
        __slots__ = ["flux_expr", "dependencies", "repr_op"]

    class FluxBatch(Record):
        __slots__ = ["flux_exprs", "repr_op"]

    def __init__(self, prefix="_expr", max_vectors_in_batch_expr=None):
        super(OperatorCompiler, self).__init__()
        self.prefix = prefix

        self.max_vectors_in_batch_expr = max_vectors_in_batch_expr

        self.code = []
        self.expr_to_var = {}

        self.assigned_names = set()

    # {{{ collecting various optemplate components ----------------------------
    def get_contained_fluxes(self, expr):
        """Recursively enumerate all flux expressions in the expression tree
        `expr`. The returned list consists of `ExecutionPlanner.FluxRecord`
        instances with fields `flux_expr` and `dependencies`.
        """

        contained_flux_ops = mappers.FluxCollector()(expr)

        from pytools import all
        assert all(isinstance(op, sym.WholeDomainFluxOperator)
                for op in contained_flux_ops), \
                        "not all flux operators were of the expected type"

        return [self.FluxRecord(
            flux_expr=wdflux,
            dependencies=set(wdflux.interior_deps) | set(wdflux.boundary_deps),
            repr_op=wdflux.repr_op())
            for wdflux in contained_flux_ops]

    def collect_diff_ops(self, expr):
        return mappers.BoundOperatorCollector(sym.ReferenceDiffOperatorBase)(expr)

    def collect_flux_exchange_ops(self, expr):
        return mappers.FluxExchangeCollector()(expr)

    # }}}

    # {{{ top-level driver ----------------------------------------------------
    def __call__(self, expr, type_hints={}):
        # Put the result expressions into variables as well.
        expr = sym.cse(expr, "_result")

        from grudge.symbolic.mappers.type_inference import TypeInferrer
        self.typedict = TypeInferrer()(expr, type_hints)

        # {{{ flux batching
        # Fluxes can be evaluated faster in batches. Here, we find flux
        # batches that we can evaluate together.

        # For each FluxRecord, find the other fluxes its flux depends on.
        flux_queue = self.get_contained_fluxes(expr)
        for fr in flux_queue:
            fr.dependencies = set(sf.flux_expr
                    for sf in self.get_contained_fluxes(fr.flux_expr)) \
                            - set([fr.flux_expr])

        # Then figure out batches of fluxes to evaluate
        self.flux_batches = []
        admissible_deps = set()
        while flux_queue:
            present_batch = set()
            i = 0
            while i < len(flux_queue):
                fr = flux_queue[i]
                if fr.dependencies <= admissible_deps:
                    present_batch.add(fr)
                    flux_queue.pop(i)
                else:
                    i += 1

            if present_batch:
                # bin batched operators by representative operator
                batches_by_repr_op = {}
                for fr in present_batch:
                    batches_by_repr_op[fr.repr_op] = \
                            batches_by_repr_op.get(fr.repr_op, set()) \
                            | set([fr.flux_expr])

                for repr_op, batch in six.iteritems(batches_by_repr_op):
                    self.flux_batches.append(
                            self.FluxBatch(
                                repr_op=repr_op,
                                flux_exprs=list(batch)))

                admissible_deps |= set(fr.flux_expr for fr in present_batch)
            else:
                raise RuntimeError("cannot resolve flux evaluation order")

        # }}}

        # Used for diff batching

        self.diff_ops = self.collect_diff_ops(expr)

        # Flux exchange also works better when batched.
        self.flux_exchange_ops = self.collect_flux_exchange_ops(expr)

        # Finally, walk the expression and build the code.
        result = super(OperatorCompiler, self).__call__(expr)

        # FIXME: Reenable assignment aggregation
        #return Code(self.aggregate_assignments(self.code, result), result)
        return Code(self.code, result)

    # }}}

    # {{{ variables and names -------------------------------------------------
    def get_var_name(self, prefix=None):
        def generate_suffixes():
            yield ""
            i = 2
            while True:
                yield "_%d" % i
                i += 1

        def generate_plain_names():
            i = 0
            while True:
                yield self.prefix + str(i)
                i += 1

        if prefix is None:
            for name in generate_plain_names():
                if name not in self.assigned_names:
                    break
        else:
            for suffix in generate_suffixes():
                name = prefix + suffix
                if name not in self.assigned_names:
                    break

        self.assigned_names.add(name)
        return name

    def assign_to_new_var(self, expr, priority=0, prefix=None,
            is_scalar_valued=False):
        from pymbolic.primitives import Variable, Subscript

        # Observe that the only things that can be legally subscripted in
        # grudge are variables. All other expressions are broken down into
        # their scalar components.
        if isinstance(expr, (Variable, Subscript)):
            return expr

        new_name = self.get_var_name(prefix)
        self.code.append(self.make_assign(
            new_name, expr, priority, is_scalar_valued))

        return Variable(new_name)

    # }}}

    # {{{ map_xxx routines

    def map_common_subexpression(self, expr):
        try:
            return self.expr_to_var[expr.child]
        except KeyError:
            priority = getattr(expr, "priority", 0)

            from grudge.symbolic.mappers.type_inference import type_info
            is_scalar_valued = isinstance(self.typedict[expr], type_info.Scalar)

            if isinstance(expr.child, sym.OperatorBinding):
                # We need to catch operator bindings here and
                # treat them specially. They get assigned to their
                # own variable by default, which would mean the
                # CSE prefix would be omitted, making the resulting
                # code less readable.
                rec_child = self.map_operator_binding(
                        expr.child, name_hint=expr.prefix)
            else:
                rec_child = self.rec(expr.child)

            cse_var = self.assign_to_new_var(rec_child,
                    priority=priority, prefix=expr.prefix,
                    is_scalar_valued=is_scalar_valued)

            self.expr_to_var[expr.child] = cse_var
            return cse_var

    def map_operator_binding(self, expr, name_hint=None):
        from grudge.symbolic.operators import (
                ReferenceDiffOperatorBase,
                FluxOperatorBase)

        if isinstance(expr.op, ReferenceDiffOperatorBase):
            return self.map_ref_diff_op_binding(expr)
        elif isinstance(expr.op, FluxOperatorBase):
            raise RuntimeError("OperatorCompiler encountered a flux operator.\n\n"
                    "We are expecting flux operators to be converted to custom "
                    "flux assignment instructions, but the subclassed compiler "
                    "does not seem to have done this.")
        else:
            # make sure operator assignments stand alone and don't get muddled
            # up in vector math
            field_var = self.assign_to_new_var(
                    self.rec(expr.field))
            result_var = self.assign_to_new_var(
                    expr.op(field_var),
                    prefix=name_hint)
            return result_var

    def map_ones(self, expr):
        # make sure expression stands alone and doesn't get
        # muddled up in vector math
        return self.assign_to_new_var(expr, prefix="ones")

    def map_node_coordinate_component(self, expr):
        # make sure expression stands alone and doesn't get
        # muddled up in vector math
        return self.assign_to_new_var(expr, prefix="nodes%d" % expr.axis)

    def map_normal_component(self, expr):
        # make sure expression stands alone and doesn't get
        # muddled up in vector math
        return self.assign_to_new_var(expr, prefix="normal%d" % expr.axis)

    def map_call(self, expr):
        from grudge.symbolic.primitives import CFunction
        if isinstance(expr.function, CFunction):
            return super(OperatorCompiler, self).map_call(expr)
        else:
            # If it's not a C-level function, it shouldn't get muddled up into
            # a vector math expression.

            return self.assign_to_new_var(
                    type(expr)(
                        expr.function,
                        [self.assign_to_new_var(self.rec(par))
                            for par in expr.parameters]))

    def map_ref_diff_op_binding(self, expr):
        try:
            return self.expr_to_var[expr]
        except KeyError:
            all_diffs = [diff
                    for diff in self.diff_ops
                    if diff.op.equal_except_for_axis(expr.op)
                    and diff.field == expr.field]

            names = [self.get_var_name() for d in all_diffs]

            from pytools import single_valued
            op_class = single_valued(type(d.op) for d in all_diffs)

            from grudge.symbolic.operators import \
                    ReferenceQuadratureStiffnessTOperator
            if isinstance(op_class, ReferenceQuadratureStiffnessTOperator):
                assign_class = QuadratureDiffBatchAssign
            else:
                assign_class = DiffBatchAssign

            self.code.append(
                    assign_class(
                        names=names,
                        op_class=op_class,
                        operators=[d.op for d in all_diffs],
                        field=self.rec(
                            single_valued(d.field for d in all_diffs))))

            from pymbolic import var
            for n, d in zip(names, all_diffs):
                self.expr_to_var[d] = var(n)

            return self.expr_to_var[expr]

    def map_flux_exchange(self, expr):
        try:
            return self.expr_to_var[expr]
        except KeyError:
            from pytools.obj_array import obj_array_equal
            all_flux_xchgs = [fe
                    for fe in self.flux_exchange_ops
                    if obj_array_equal(fe.arg_fields, expr.arg_fields)]

            assert len(all_flux_xchgs) > 0

            names = [self.get_var_name() for d in all_flux_xchgs]
            self.code.append(
                    FluxExchangeBatchAssign(
                        names=names,
                        indices_and_ranks=[
                            (fe.index, fe.rank)
                            for fe in all_flux_xchgs],
                        arg_fields=[
                            self.rec(arg_field)
                            for arg_field in fe.arg_fields]))

            from pymbolic import var
            for n, d in zip(names, all_flux_xchgs):
                self.expr_to_var[d] = var(n)

            return self.expr_to_var[expr]

    def map_planned_flux(self, expr):
        try:
            return self.expr_to_var[expr]
        except KeyError:
            for fb in self.flux_batches:
                try:
                    idx = fb.flux_exprs.index(expr)
                except ValueError:
                    pass
                else:
                    # found at idx
                    mapped_fluxes = [
                            self.internal_map_flux(f)
                            for f in fb.flux_exprs]

                    names = [self.get_var_name() for f in mapped_fluxes]
                    self.code.append(
                            self.make_flux_batch_assign(
                                names, mapped_fluxes, fb.repr_op))

                    from pymbolic import var
                    for n, f in zip(names, fb.flux_exprs):
                        self.expr_to_var[f] = var(n)

                    return var(names[idx])

            raise RuntimeError("flux '%s' not in any flux batch" % expr)

    # }}}

    # {{{ instruction producers

    def make_assign(self, name, expr, priority, is_scalar_valued=False):
        return Assign(names=[name], exprs=[expr],
                priority=priority,
                is_scalar_valued=is_scalar_valued)

    def make_flux_batch_assign(self, names, expressions, repr_op):
        return FluxBatchAssign(names=names, expressions=expressions, repr_op=repr_op)

    # from CUDA backend:
    # def make_flux_batch_assign(self, names, expressions, repr_op):
    #     from pytools import single_valued
    #     quadrature_tag = single_valued(
    #             wdflux.quadrature_tag
    #             for wdflux in expressions)

    #     return CUDAFluxBatchAssign(
    #             names=names, expressions=expressions, repr_op=repr_op,
    #             quadrature_tag=quadrature_tag)

    # }}}

    # {{{ assignment aggregration pass

    def aggregate_assignments(self, instructions, result):
        from pymbolic.primitives import Variable

        # {{{ aggregation helpers

        def get_complete_origins_set(insn, skip_levels=0):
            if skip_levels < 0:
                skip_levels = 0

            result = set()
            for dep in insn.get_dependencies():
                if isinstance(dep, Variable):
                    dep_origin = origins_map.get(dep.name, None)
                    if dep_origin is not None:
                        if skip_levels <= 0:
                            result.add(dep_origin)
                        result |= get_complete_origins_set(
                                dep_origin, skip_levels-1)

            return result

        var_assignees_cache = {}

        def get_var_assignees(insn):
            try:
                return var_assignees_cache[insn]
            except KeyError:
                result = set(Variable(assignee)
                        for assignee in insn.get_assignees())
                var_assignees_cache[insn] = result
                return result

        def aggregate_two_assignments(ass_1, ass_2):
            names = ass_1.names + ass_2.names

            from pymbolic.primitives import Variable
            deps = (ass_1.get_dependencies() | ass_2.get_dependencies()) \
                    - set(Variable(name) for name in names)

            return Assign(
                    names=names, exprs=ass_1.exprs + ass_2.exprs,
                    _dependencies=deps,
                    priority=max(ass_1.priority, ass_2.priority))

        # }}}

        # {{{ main aggregation pass

        origins_map = dict(
                    (assignee, insn)
                    for insn in instructions
                    for assignee in insn.get_assignees())

        from pytools import partition
        unprocessed_assigns, other_insns = partition(
                lambda insn: isinstance(insn, Assign) and not insn.is_scalar_valued,
                instructions)

        # filter out zero-flop-count assigns--no need to bother with those
        processed_assigns, unprocessed_assigns = partition(
                lambda ass: ass.flop_count() == 0,
                unprocessed_assigns)

        # filter out zero assignments
        from pytools import any
        from grudge.tools import is_zero

        i = 0

        while i < len(unprocessed_assigns):
            my_assign = unprocessed_assigns[i]
            if any(is_zero(expr) for expr in my_assign.exprs):
                processed_assigns.append(unprocessed_assigns.pop())
            else:
                i += 1

        # greedy aggregation
        while unprocessed_assigns:
            my_assign = unprocessed_assigns.pop()

            my_deps = my_assign.get_dependencies()
            my_assignees = get_var_assignees(my_assign)

            agg_candidates = []
            for i, other_assign in enumerate(unprocessed_assigns):
                other_deps = other_assign.get_dependencies()
                other_assignees = get_var_assignees(other_assign)

                if ((my_deps & other_deps
                        or my_deps & other_assignees
                        or other_deps & my_assignees)
                        and my_assign.priority == other_assign.priority):
                    agg_candidates.append((i, other_assign))

            did_work = False

            if agg_candidates:
                my_indirect_origins = get_complete_origins_set(
                        my_assign, skip_levels=1)

                for other_assign_index, other_assign in agg_candidates:
                    if self.max_vectors_in_batch_expr is not None:
                        new_assignee_count = len(
                                set(my_assign.get_assignees())
                                | set(other_assign.get_assignees()))
                        new_dep_count = len(
                                my_assign.get_dependencies(
                                    each_vector=True)
                                | other_assign.get_dependencies(
                                    each_vector=True))

                        if (new_assignee_count + new_dep_count
                                > self.max_vectors_in_batch_expr):
                            continue

                    other_indirect_origins = get_complete_origins_set(
                            other_assign, skip_levels=1)

                    if (my_assign not in other_indirect_origins and
                            other_assign not in my_indirect_origins):
                        did_work = True

                        # aggregate the two assignments
                        new_assignment = aggregate_two_assignments(
                                my_assign, other_assign)
                        del unprocessed_assigns[other_assign_index]
                        unprocessed_assigns.append(new_assignment)
                        for assignee in new_assignment.get_assignees():
                            origins_map[assignee] = new_assignment

                        break

            if not did_work:
                processed_assigns.append(my_assign)

        externally_used_names = set(
                expr
                for insn in processed_assigns + other_insns
                for expr in insn.get_dependencies())

        from pytools.obj_array import is_obj_array
        if is_obj_array(result):
            externally_used_names |= set(expr for expr in result)
        else:
            externally_used_names |= set([result])

        def schedule_and_finalize_assignment(ass):
            dep_mapper = _make_dep_mapper(include_subscripts=False)

            names_exprs = list(zip(ass.names, ass.exprs))

            my_assignees = set(name for name, expr in names_exprs)
            names_exprs_deps = [
                    (name, expr,
                        set(dep.name for dep in dep_mapper(expr) if
                            isinstance(dep, Variable)) & my_assignees)
                    for name, expr in names_exprs]

            ordered_names_exprs = []
            available_names = set()

            while names_exprs_deps:
                schedulable = []

                i = 0
                while i < len(names_exprs_deps):
                    name, expr, deps = names_exprs_deps[i]

                    unsatisfied_deps = deps - available_names

                    if not unsatisfied_deps:
                        schedulable.append((str(expr), name, expr))
                        del names_exprs_deps[i]
                    else:
                        i += 1

                # make sure these come out in a constant order
                schedulable.sort()

                if schedulable:
                    for key, name, expr in schedulable:
                        ordered_names_exprs.append((name, expr))
                        available_names.add(name)
                else:
                    raise RuntimeError("aggregation resulted in an "
                            "impossible assignment")

            return self.finalize_multi_assign(
                    names=[name for name, expr in ordered_names_exprs],
                    exprs=[expr for name, expr in ordered_names_exprs],
                    do_not_return=[Variable(name) not in externally_used_names
                        for name, expr in ordered_names_exprs],
                    priority=ass.priority)

        return [schedule_and_finalize_assignment(ass)
            for ass in processed_assigns] + other_insns

        # }}}

    # }}}

    def internal_map_flux(self, wdflux):
        return sym.WholeDomainFluxOperator(
            wdflux.is_lift,
            [wdflux.InteriorInfo(
                flux_expr=ii.flux_expr,
                field_expr=self.rec(ii.field_expr))
                for ii in wdflux.interiors],
            [wdflux.BoundaryInfo(
                flux_expr=bi.flux_expr,
                bpair=self.rec(bi.bpair))
                for bi in wdflux.boundaries],
            wdflux.quadrature_tag)

    def map_whole_domain_flux(self, wdflux):
        return self.map_planned_flux(wdflux)

    def finalize_multi_assign(self, names, exprs, do_not_return, priority):
        return VectorExprAssign(names=names, exprs=exprs,
                do_not_return=do_not_return,
                priority=priority)

# }}}


# vim: foldmethod=marker