"""
.. currentmodule:: grudge.op

Projections
-----------

.. autofunction:: project
"""

from __future__ import annotations

__copyright__ = """
Copyright (C) 2021 University of Illinois Board of Trustees
"""

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


from arraycontext import ArrayOrContainer

from grudge.discretization import DiscretizationCollection
from grudge.dof_desc import as_dofdesc

from numbers import Number


def project(
        dcoll: DiscretizationCollection, src, tgt, vec) -> ArrayOrContainer:
    """Project from one discretization to another, e.g. from the
    volume to the boundary, or from the base to the an overintegrated
    quadrature discretization.

    :arg src: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one.
    :arg tgt: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one.
    :arg vec: a :class:`~meshmode.dof_array.DOFArray` or an
        :class:`~arraycontext.ArrayContainer` of them.
    :returns: a :class:`~meshmode.dof_array.DOFArray` or an
        :class:`~arraycontext.ArrayContainer` like *vec*.
    """
    src = as_dofdesc(src)
    tgt = as_dofdesc(tgt)

    if isinstance(vec, Number) or src == tgt:
        return vec

    return dcoll.connection_from_dds(src, tgt)(vec)
