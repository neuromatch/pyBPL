"""
B-splines utilities. For reference material on B-splines, see Kristin Branson's
"A Practical Review of Uniform B-splines":
http://vision.ucsd.edu/~kbranson/research/bsplines/bsplines.pdf
"""
from __future__ import division, print_function
import math
import torch

from .parameters import defaultps
from .util.general import least_squares
from .util.stroke import dist_along_traj


def vectorized_bspline_coeff(vi, vs):
    """
    TODO: what does this do exactly?
    see Kristin Branson's "A Practical Review of Uniform B-splines"

    Parameters
    ----------
    vi : (neval,nland) tensor
    vs : (neval,nland) tensor

    Returns
    -------
    C : (neval,nland)
        coefficients
    """
    assert vi.shape == vs.shape
    assert vi.dtype == vs.dtype

    # step through the conditions
    # NOTE: in the following, * stands in for 'and'
    C = torch.zeros_like(vi, dtype=torch.float)

    # sel1
    sel = (vs >= vi)*(vs < vi+1)
    diff = vs[sel] - vi[sel]
    val = torch.pow(diff, 3)
    C[sel] = val/6.
    # sel2
    sel = (vs >= vi+1)*(vs < vi+2)
    diff = vs[sel] - vi[sel] - 1
    val = -3*torch.pow(diff, 3) + 3*torch.pow(diff, 2) + 3*diff + 1
    C[sel] = val/6.
    # sel3
    sel = (vs >= vi+2)*(vs < vi+3)
    diff = vs[sel] - vi[sel] - 2
    val = 3*torch.pow(diff, 3) - 6*torch.pow(diff, 2) + 4
    C[sel] = val/6.
    # sel4
    sel = (vs >= vi+3)*(vs < vi+4)
    diff = vs[sel] - vi[sel] - 3
    val = torch.pow(1-diff, 3)
    C[sel] = val/6.

    return C

def bspline_gen_s(nland, neval=200):
    """
    Generate time points for evaluating spline.
    The convex-combination of the endpoints with five control points are 80
    percent of the last cpt and 20 percent of the control point after that.

    Parameters
    ----------
    nland : int
        number of landmarks (control points)
    neval : int
        number of eval points

    Returns
    -------
    s : (neval,) tensor
        time points for spline eval
    lb : TODO
    ub : TODO
    """
    lb = torch.tensor(2, dtype=torch.float)
    ub = torch.tensor(nland+1, dtype=torch.float)
    if neval == 1:
        s = torch.tensor([lb], dtype=torch.float)
    else:
        s = torch.linspace(lb, ub, neval)

    return s, lb, ub

def bspline_eval(s, Y):
    """
    Produce a trajectory from a B-spline.

    Parameters
    ----------
    s : (neval,) tensor
        time points for spline eval
    Y : (nland,2) tensor
        input spline (control points)

    Returns
    -------
    X : (neval,2) tensor
        output trajectory
    Cof : (neval, nland) tensor
        TODO
    """
    if s.shape == torch.Size([]):
        s = s.view(1)
    assert len(s.shape) == 1
    assert len(Y.shape) == 2 and Y.shape[1] == 2
    neval = s.shape[0]
    nland = Y.shape[0]

    # compute spline coefficients
    S = s.unsqueeze(1).repeat(1,nland) # (neval, nland)
    I = torch.arange(nland).unsqueeze(0).repeat(neval, 1).float() # (neval, nland)
    A = vectorized_bspline_coeff(I, S) # (neval, nland)
    Cof = A / torch.sum(A, dim=1, keepdim=True) # (neval, nland)

    # (neval,nland) @ (nland,2) = (neval,2)
    X = Cof @ Y

    return X, Cof

def bspline_fit(s, X, nland, include_resid=False):
    """
    Produce a B-spline from a trajectory (via least-squares).

    Parameters
    ----------
    s : (neval,) tensor
        time points for spline eval
    X : (neval,2) tensor
        input trajectory
    nland : int
        number of landmarks (control points) for the spline
    include_resid : bool
        whether to return the residuals of the least-squares problem

    Returns
    -------
    Y : (nland,2) tensor
        output spline
    residuals : (2,) tensor
        (optional) residuals of the least-squares problem
    """
    neval = s.size(0)
    assert X.shape == (neval, 2)

    # compute spline coefficients
    S = s.unsqueeze(1).repeat(1,nland) # (neval, nland)
    I = torch.arange(nland).unsqueeze(0).repeat(neval, 1).float() # (neval, nland)
    A = vectorized_bspline_coeff(I, S) # (neval, nland)
    Cof = A / torch.sum(A, dim=1, keepdim=True) # (neval, nland)

    # solve least squares problem
    Y, residuals, _, _ = least_squares(Cof, X) # (nland, 2)

    if include_resid:
        return Y, residuals
    else:
        return Y

def get_stk_from_bspline(Y, neval=None):
    """
    Produce a trajectory from a B-spline.
    NOTE: this is a wrapper for bspline_eval (first produces time points)

    Parameters
    ----------
    Y : (nland,2) tensor
        input spline (control points)
    neval : int
        number of eval points

    Returns
    -------
    X : (neval,2) tensor
        output trajectory
    """
    assert isinstance(Y, torch.Tensor)
    assert len(Y.shape) == 2 and Y.shape[1] == 2
    nland = Y.shape[0]

    # if `neval` is None, set it adaptively according to stroke size
    if neval is None:
        params = defaultps()
        min_neval = params.spline_min_neval
        max_neval = params.spline_max_neval
        spl_grain = params.spline_grain
        # check the stroke size
        s, _, _ = bspline_gen_s(nland, min_neval)
        stk, _ = bspline_eval(s, Y)
        dist = dist_along_traj(stk)
        # set neval based on stroke size
        neval = math.ceil(dist/spl_grain)
        # threshold
        neval = max(neval, min_neval)
        neval = min(neval, max_neval)

    # generate time points
    s, _, _ = bspline_gen_s(nland, neval)
    # compute trajectory
    X, _ = bspline_eval(s, Y)

    return X

def fit_bspline_to_traj(X, nland, include_resid=False):
    """
    Produce a B-spline from a trajectory (via least-squares).
    NOTE: this is a wrapper for bspline_fit (first produces time points)

    Parameters
    ----------
    X : (neval,2) tensor
        input trajectory
    nland : int
        number of landmarks (control points)
    include_resid : bool
        whether to return the residuals of the least-squares problem

    Returns
    -------
    Y : (nland,2) tensor
        output spline
    residuals : (2,) tensor
        (optional) residuals of the least-squares problem
    """
    assert isinstance(X, torch.Tensor)
    assert len(X.shape) == 2 and X.shape[1] == 2

    # generate time points
    s, _, _ = bspline_gen_s(nland, neval=len(X))
    # compute spline
    if include_resid:
        Y, residuals = bspline_fit(s, X, nland, include_resid=True)
        return Y, residuals
    else:
        Y = bspline_fit(s, X, nland, include_resid=False)
        return Y
