"""
Relations for sampling part positions. Relations, together with parts, make up
concepts.
"""
from __future__ import print_function, division
from abc import ABCMeta, abstractmethod
import torch
import torch.distributions as dist

from .part import PartToken
from .splines import bspline_eval, bspline_gen_s

categories_allowed = ['unihist', 'start', 'end', 'mid']




class RelationToken(object):
    """
    TODO

    Parameters
    ----------
    rel : TODO
        TODO
    kwargs : TODO
        TODO
    """
    def __init__(self, rel, **kwargs):
        self.rel = rel
        if rel.category in ['unihist', 'start', 'end']:
            assert kwargs == {}
        else:
            assert set(kwargs.keys()) == {'eval_spot_token'}
            self.eval_spot_token = kwargs['eval_spot_token']

    def sample_location(self, prev_parts):
        """
        TODO

        Parameters
        ----------
        prev_parts : list of PartToken
            previous part tokens

        Returns
        -------
        loc : tensor
            location; x-y coordinates

        """
        for pt in prev_parts:
            assert isinstance(pt, PartToken)
        base = self.get_attach_point(prev_parts)
        assert base.shape == torch.Size([2])
        loc = base + self.rel.loc_dist.sample()

        return loc

    def score_location(self, loc, prev_parts):
        """
        TODO

        Parameters
        ----------
        loc : TODO
            TODO
        prev_parts : TODO
            TODO

        Returns
        -------
        ll : tensor
            TODO

        """
        for pt in prev_parts:
            assert isinstance(pt, PartToken)
        base = self.get_attach_point(prev_parts)
        assert base.shape == torch.Size([2])
        ll = self.rel.loc_dist.log_prob(loc - base)

        return ll

    def get_attach_point(self, prev_parts):
        """
        Get the mean attachment point of where the start of the next part
        should be, given the previous part tokens.

        Parameters
        ----------
        prev_parts : TODO
            TODO

        Returns
        -------
        loc : TODO
            TODO

        """
        if self.rel.category == 'unihist':
            loc = self.rel.gpos
        else:
            prev = prev_parts[self.rel.attach_ix]
            if self.rel.category == 'start':
                subtraj = prev.motor[0]
                loc = subtraj[0]
            elif self.rel.category == 'end':
                subtraj = prev.motor[-1]
                loc = subtraj[-1]
            else:
                assert self.rel.category == 'mid'
                bspline = prev.motor_spline[:, :, self.rel.attach_subix]
                loc, _ = bspline_eval(self.eval_spot_token, bspline)
                # convert (1,2) tensor -> (2,) tensor
                loc = torch.squeeze(loc, dim=0)

        return loc


class Relation(object):
    """
    TODO

    Parameters
    ----------
    category : string
        relation category
    lib : Library
        library instance, which holds token-level distribution parameters
    """
    __metaclass__ = ABCMeta

    def __init__(self, category, lib):
        # make sure type is valid
        assert category in categories_allowed
        self.category = category
        # token-level position distribution parameters
        sigma_x = lib.rel['sigma_x']
        sigma_y = lib.rel['sigma_y']
        loc_Cov = torch.tensor([[sigma_x, 0.], [0., sigma_y]])
        self.loc_dist = dist.MultivariateNormal(torch.zeros(2), loc_Cov)

    def sample_token(self):
        """
        TODO

        Returns
        -------
        rtoken : RelationToken
            TODO
        """
        rtoken = RelationToken(self)

        return rtoken

    def score_token(self, token):
        """
        TODO

        Parameters
        ----------
        token : RelationToken
            TODO

        Returns
        -------
        ll : tensor
            TODO

        """
        ll = torch.tensor(0.)

        return ll


class RelationIndependent(Relation):
    """
    TODO

    Parameters
    ----------
    category : string
        relation category
    gpos : (2,) tensor
        position; x-y coordinates
    lib : Library
        library instance, which holds token-level distribution parameters
    """
    def __init__(self, category, gpos, lib):
        super(RelationIndependent, self).__init__(category, lib)
        assert category == 'unihist'
        assert gpos.shape == torch.Size([2])
        self.gpos = gpos


class RelationAttach(Relation):
    """
    TODO

    Parameters
    ----------
    category : string
        relation category
    attach_ix : int
        index of previous part to which this part will attach
    lib : Library
        library instance, which holds token-level distribution parameters
    """
    def __init__(self, category, attach_ix, lib):
        super(RelationAttach, self).__init__(category, lib)
        assert category in ['start', 'end', 'mid']
        self.attach_ix = attach_ix


class RelationAttachAlong(RelationAttach):
    """
    TODO

    Parameters
    ----------
    category : string
        relation category
    attach_ix : int
        index of previous part to which this part will attach
    attach_subix : int
        index of sub-stroke from the selected previous part to which
        this part will attach
    eval_spot : tensor
        type-level spline coordinate
    lib : Library
        library instance, which holds token-level distribution parameters
    """
    def __init__(self, category, attach_ix, attach_subix, eval_spot, lib):
        super(RelationAttachAlong, self).__init__(category, attach_ix, lib)
        assert category == 'mid'
        self.attach_subix = attach_subix
        self.ncpt = lib.ncpt
        # token-level eval_spot distribution parameters
        sigma_attach = lib.tokenvar['sigma_attach']
        self.eval_spot_dist = dist.normal.Normal(eval_spot, sigma_attach)

    def sample_token(self):
        """
        TODO

        Returns
        -------
        token : RelationToken
            TODO
        """
        eval_spot_token = self.sample_eval_spot_token()
        token = RelationToken(self, eval_spot_token=eval_spot_token)

        return token

    def score_token(self, token):
        """
        TODO

        Parameters
        ----------
        token : RelationToken
            TODO

        Returns
        -------
        ll : tensor
            TODO
        """
        assert hasattr(token, 'eval_spot_token')
        ll = self.score_eval_spot_token(token.eval_spot_token)

        return ll

    def sample_eval_spot_token(self):
        """
        TODO

        Returns
        -------
        eval_spot_token : tensor
            token-level spline coordinate
        """
        ll = torch.tensor(-float('inf'))
        while ll == -float('inf'):
            eval_spot_token = self.eval_spot_dist.sample()
            ll = self.score_eval_spot_token(eval_spot_token)

        return eval_spot_token

    def score_eval_spot_token(self, eval_spot_token):
        """
        TODO

        Parameters
        ----------
        eval_spot_token : tensor
            token-level spline coordinate

        Returns
        -------
        ll : tensor
            TODO
        """
        assert type(eval_spot_token) in [int, float] or \
               (type(eval_spot_token) == torch.Tensor and
                eval_spot_token.shape == torch.Size([]))
        _, lb, ub = bspline_gen_s(self.ncpt, 1)
        if eval_spot_token < lb or eval_spot_token > ub:
            ll = torch.tensor(-float('inf'))
            return ll
        ll = self.eval_spot_dist.log_prob(eval_spot_token)

        # correction for bounds
        p_within = self.eval_spot_dist.cdf(ub) - self.eval_spot_dist.cdf(lb)
        ll = ll - torch.log(p_within)

        return ll
