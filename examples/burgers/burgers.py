"""Minimal example of a grudge driver."""

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

import os
import numpy as np

import pyopencl as cl

from meshmode.array_context import PyOpenCLArrayContext
from meshmode.dof_array import thaw, flatten

from pytools.obj_array import flat_obj_array

import grudge.dof_desc as dof_desc
import grudge.op as op

import logging
logger = logging.getLogger(__name__)


# {{{ plotting (keep in sync with `weak.py`)

class Plotter:
    def __init__(self, actx, dcoll, order, visualize=True, ylim=None):
        self.actx = actx
        self.dim = dcoll.ambient_dim

        self.visualize = visualize
        if not self.visualize:
            return

        if self.dim == 1:
            import matplotlib.pyplot as pt
            self.fig = pt.figure(figsize=(8, 8), dpi=300)
            self.ylim = ylim

            volume_discr = dcoll.discr_from_dd(dof_desc.DD_VOLUME)
            self.x = actx.to_numpy(flatten(thaw(actx, volume_discr.nodes()[0])))
        else:
            from grudge.shortcuts import make_visualizer
            self.vis = make_visualizer(dcoll)

    def __call__(self, evt, basename, overwrite=True):
        if not self.visualize:
            return

        if self.dim == 1:
            u = self.actx.to_numpy(flatten(evt.state_component))

            filename = "%s.png" % basename
            if not overwrite and os.path.exists(filename):
                from meshmode import FileExistsError
                raise FileExistsError("output file '%s' already exists" % filename)

            ax = self.fig.gca()
            ax.plot(self.x, u, "-")
            ax.plot(self.x, u, "k.")
            if self.ylim is not None:
                ax.set_ylim(self.ylim)

            ax.set_xlabel("$x$")
            ax.set_ylabel("$u$")
            ax.set_title(f"t = {evt.t:.2f}")
            self.fig.savefig(filename)
            self.fig.clf()
        else:
            self.vis.write_vtk_file("%s.vtu" % basename, [
                ("u", evt.state_component)
                ], overwrite=overwrite)

# }}}

def main(ctx_factory, dim=1, order=4, visualize=False):
    cl_ctx = ctx_factory()
    queue = cl.CommandQueue(cl_ctx)
    actx = PyOpenCLArrayContext(queue)

    # {{{ parameters

    # domain [0, d]^dim
    d = 2*np.pi
    # number of points in each dimension
    npoints = 25
    # grid spacing
    h = d / npoints

    # cfl
    dt_factor = 1.0
    # finale time
    final_time = 0.5
    # time steps
    dt = dt_factor * h/order**2
    nsteps = int(final_time // dt) + 1
    dt = final_time/nsteps + 1.0e-15

    # flux
    flux_type = "central"

    # }}}

    # {{{ discretization

    from meshmode.mesh.generation import generate_regular_rect_mesh
    mesh = generate_regular_rect_mesh(
            a=(0,)*dim, b=(d,)*dim,
            npoints_per_axis=(npoints,)*dim,
            order=order)

    discr_tag_to_group_factory = {}

    from grudge import DiscretizationCollection

    dcoll = DiscretizationCollection(
        actx, mesh, order=order,
        discr_tag_to_group_factory=discr_tag_to_group_factory
    )

    # }}}

    # {{{ Burgers operator

    from grudge.models.burgers import InviscidBurgers

    x = thaw(actx, op.nodes(dcoll))

    # velocity field
    if dim == 1:
        u_init = actx.np.sin(x)
    else:
        raise NotImplementedError()

    burgers_operator = InviscidBurgers(
        dcoll,
        flux_type=flux_type
    )

    def rhs(t, u):
        return burgers_operator.operator(t, u)

    # }}}

    # {{{ time stepping

    from grudge.shortcuts import set_up_rk4
    dt_stepper = set_up_rk4("u", dt, u, rhs)
    plot = Plotter(actx, dcoll, order, visualize=visualize, ylim=[-1.1, 1.1])

    step = 0
    for event in dt_stepper.run(t_end=final_time):
        if not isinstance(event, dt_stepper.StateComputed):
            continue

        if step % 10 == 0:
            norm_u = op.norm(dcoll, event.state_component, 2)
            plot(event, "fld-burgers-%04d" % step)

        step += 1
        logger.info("[%04d] t = %.5f |u| = %.5e", step, event.t, norm_u)

    # }}}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dim", default=1, type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    main(cl.create_some_context,
            dim=args.dim)
