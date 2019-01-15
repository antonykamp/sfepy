import numpy as nm
from sfepy.terms.terms import Term

from dg_field import get_unraveler, get_raveler



def unravel_sol(state):
    """
    Unpacks solution from flat vector to
    (n_cell, n_el_nod, n_comp)


    :param state:
    """

    u = state.data[0]  # this uses data provided by solver
    # this uses data provided by solver
    # ur = self.get(state, 'dg', step=-1)
    # however this would probably too,
    # as they are set to variable in equation

    # in 2D+ case this will be replaced by get_nbrhd_dofs

    n_cell = state.field.n_cell
    n_el_nod = state.field.poly_space.n_nod
    unravel = get_unraveler(n_el_nod, n_cell)
    return unravel(u)


class AdvVolDGTerm(Term):

    name = "dw_dg_volume"
    modes = ("weak",)
    arg_types = ('virtual', 'state')
    # arg_types = ('ts', 'virtual', 'state')
    arg_shapes = {'virtual': 1, #('D', 'state'),
                  'state': 1}
    symbolic = {'expression': '1',
                'map': {'u': 'state'}
                }

    def __init__(self, integral, region, u=None, v=None):
        Term.__init__(self, "adv_vol(v, u)", "v, u", integral, region, u=u, v=v)
        self.u = u
        self.v = v
        self.setup()

    def get_fargs(self, test, state,
                  mode=None, term_mode=None, diff_var=None, **kwargs):
        if diff_var is not None:
            mtx_mode = True
            u = None
        else:
            mtx_mode = False
            u = unravel_sol(state)

        dim = state.field.dim
        n_el_nod = state.field.poly_space.n_nod
        vols = self.region.domain.cmesh.get_volumes(dim)[:, None]
        return u, mtx_mode, n_el_nod, vols

    def function(self, out, u, mtx_mode, n_el_nod, vols):
        if mtx_mode:
            # integral over element with constant test
            # function is just volume of the element
            out[:] = 0.0
            # out[:, 0, 0, 0] = vols
            # out[:, 0, 1, 1] = vols / 3.0
            for i in range(n_el_nod):
                # these are values for legendre basis in 1D!
                out[:, :, i, i] = vols / (2.0 * i + 1.0)
        else:
            out[:] = 0.0
            for i in range(n_el_nod):
                out[:, :, i, 0] = vols / (2.0 * i + 1.0) * u[:, i]
                # TODO does this hold for higher orders and dimensions?! -  seems like it does...
        status = None
        return status


class AdvFluxDGTerm1D(Term):

    def __init__(self, integral, region, u=None, v=None, a=lambda x: 1):
        Term.__init__(self, "adv_lf_flux(a.val, v, u)", "a.val, v, u", integral, region, u=u, v=v, a=a)
        self.u = u
        self.v = v
        self.a = a
        self.setup()

    name = "dw_dg_advect_flux"
    modes = ("weak",)
    arg_types = ('material', 'virtual', 'state')
    arg_shapes = {'material': 'D, 1',
                  'virtual': ('D', 'state'),
                  'state'   : 1}
    symbolic = {'expression' : 'grad(a*u)',
                'map': {'u': 'state', 'a': 'material'}
    }

    def get_fargs(self, a, test, state,
                  mode=None, term_mode=None, diff_var=None, **kwargs):

        if diff_var is not None:
            # do not eval in matrix mode, we however still need
            # this term to have diff_var in order for it to receive the values
            doeval = False
            return None, None, None, None, doeval, 0, 0
        else:
            doeval = True

            u = unravel_sol(state)  # TODO we unravel twice, refactor
            n_el_nod = state.field.poly_space.n_nod
            n_el_facets = state.field.n_el_facets
            nb_dofs, nb_normals = state.field.get_nbrhd_dofs(state.field.region, state)
            # state variable has dt in it!

            fargs = (u, nb_dofs, nb_normals, a[:, :1, 0, 0], doeval, n_el_nod, n_el_facets)
            return fargs

    def function(self, out, u, nb_u, nb_n, velo, doeval, n_el_nod, n_el_facets):
        if not doeval:
            out[:] = 0.0
            return None

        #  the Lax-Friedrichs flux is

        #       F(a, b) = 1/2(f(a) + f(b)) + max(|f'(w)|) / 2 * (a - b)

        # in our case a and b are values from elements left and right of
        # the respective element boundaries
        # for Legendre basis these are:
        # u_left = U_0 + U_1 + U_2 + ...
        # u_right = U_0 - U_1 + U_2 - U_3 ... = sum_{p=0}^{order} (-1)^p * U_p

        # left flux is calculated in j_-1/2  where U(j-1) and U(j) meet
        # right flux is calculated in j_+1/2 where U(j) and U(j+1) meet

        # fl:
        # fl = velo[:, 0] * (ul[:, 0] + ul[:, 1] +
        #                    (u[:, 0] - u[:, 1])) / 2 + \
        #      nm.abs(velo[:, 0]) * (ul[:, 0] + ul[:, 1] -
        #                            (u[:, 0] - u[:, 1])) / 2
        a = 0
        b = 0
        sign = 1
        for i in range(n_el_nod):
            a += nb_u[:, 0, i]  # integral left
            b += sign * u[:, i]
            sign *= -1

        fl = (velo * a + velo * b) / 2 + \
              nm.abs(velo) * (a - b) / 2

        # fl:
        # fp = velo[:, 0] * (u[:, 0] + u[:, 1] +
        #                            (ur[:, 0] - ur[: , 1])) / 2 + \
        #              nm.abs(velo[:, 0]) * (u[:, 0] + u[:, 1] -
        #                                    (ur[:, 0] - ur[:, 1])) / 2
        a = 0
        b = 0
        sign = 1
        for i in range(n_el_nod):
            a += u[:, i]
            b += sign * nb_u[:,1 , i]
            sign *= -1

        fp = (velo * a + velo * b) / 2 + \
              nm.abs(velo) * (a - b) / 2

        out[:] = 0.0

        # flux0 = (fl - fp)
        # flux1 = (- fl - fp + intg1)
        # out[:, 0, 0, 0] = -flux0
        # out[:, 0, 1, 0] = -flux1

        # for Legendre basis integral of higher order
        # functions of the basis is zero,
        # hence we calculate integral
        #
        # int_{j-1/2}^{j+1/2} f(u)dx
        #
        # only from the zero order function, over [-1, 1] - hence the 2
        intg1 = velo * u[:, 0] * 2
        intg2 = velo * u[:, 1] * 2 if n_el_nod > 2 else 0
        # i.e. intg1 = a * u0 * reference_el_vol

        flux = list()
        flux[:3] = (fl - fp), (- fl - fp + intg1), (fl - fp + intg2)
        for i in range(n_el_nod):
            out[:, :, i, 0] = -flux[i]


        status = None
        return status


class AdvFluxDGTerm(Term):

    def __init__(self, integral, region, u=None, v=None, a=lambda x: 1):
        Term.__init__(self, "adv_lf_flux(a.val, v, u)", "a.val, v, u", integral, region, u=u, v=v, a=a)
        self.u = u
        self.v = v
        self.a = a
        self.setup()

    name = "dw_dg_advect_flux"
    modes = ("weak",)
    arg_types = ('material', 'virtual', 'state')
    arg_shapes = {'material': 'D, 1',
                  'virtual': 1,  #('D', 'state'),
                  'state': 1}
    symbolic = {'expression' : 'grad(a*u)',
                'map': {'u': 'state', 'a': 'material'}
    }

    def get_fargs(self, a, test, state,
                  mode=None, term_mode=None, diff_var=None, **kwargs):

        if diff_var is not None:
            # do not eval in matrix mode, we however still need
            # this term to have diff_var in order for it to receive the values
            doeval = False
            u = unravel_sol(state)
            return u, None, None, None, a[:, 0, :, 0], doeval, 0, 0
        else:
            doeval = True

            field = state.field
            u = unravel_sol(state)  # TODO we unravel twice, refactor
            n_el_nod = state.field.poly_space.n_nod
            n_el_facets = state.field.n_el_facets
            nb_dofs, facet_normals = state.field.get_nbrhd_dofs(state.field.region, state)
            # state variable has dt in it!

            fargs = (u, nb_dofs, facet_normals, a[:, 0, :, 0], doeval, n_el_nod, n_el_facets, field)
            return fargs

    def function(self, out, u, nb_u, fc_n, velo, doeval, n_el_nod, n_el_facets, field):
        if not doeval:
            out[:] = 0.0
            return None

        #  the Lax-Friedrichs flux is

        #       F(a, b) = (f(a) + f(b))/2 + max(n_x * |df1(u)/du  +  n_y * df2(u)/du|) / 2 * n * (a - b)

        # in our case a and b are values from elements left and right of
        # the respective element boundaries
        # for Legendre basis these are:
        # u_left = U_0 + U_1 + U_2 + ...
        # u_right = U_0 - U_1 + U_2 - U_3 ... = sum_{p=0}^{order} (-1)^p * U_p

        # left flux is calculated in j_-1/2  where U(j-1) and U(j) meet
        # right flux is calculated in j_+1/2 where U(j) and U(j+1) meet

        # fl:
        # fl = velo[:, 0] * (ul[:, 0] + ul[:, 1] +
        #                    (u[:, 0] - u[:, 1])) / 2 + \
        #      nm.abs(velo[:, 0]) * (ul[:, 0] + ul[:, 1] -
        #                            (u[:, 0] - u[:, 1])) / 2
        facet_fluxs = self.get_facet_fluxes(u, nb_u, velo, fc_n, n_el_facets, field)

        fluxs = nm.zeros((nm.shape(out)[0], n_el_nod, 1))
        fluxs[:, 0] = - nm.sum(facet_fluxs * fc_n, axis=1)
        intg1 = velo * u[:, 0] * 2  # TODO this goes to the stifness matrix, provided by ScalarDotMGradScalarTerm
        fluxs[:, 1] = - facet_fluxs[:, 0] - facet_fluxs[:, 1] + intg1

        # flux0 = (fl - fp)
        # flux1 = (- fl - fp + intg1)

        # for Legendre basis integral of higher order
        # functions of the basis is zero,
        # hence we calculate integral
        #
        # int_{j-1/2}^{j+1/2} f(u)dx
        #
        # only from the zero order function, over [-1, 1] - hence the 2
        # TODO move this (stiffness matrix) to matrix mode?
        # intg1 = velo * u[:, 0] * 2
        # intg2 = velo * u[:, 1] * 2 if n_el_nod > 2 else 0
        # i.e. intg1 = a * u0 * reference_el_vol

        out[:] = 0.0
        for i in range(n_el_nod):
            out[:, :, i, 0] = -fluxs[:, i]


        status = None
        return status

    def get_facet_fluxes(self, dofs, nb_dofs, velo, fc_n,  n_el_facets, field):
        """
        Calculates integrals over facets representing Lax-Firedrichs fluxes, returns them for cells and neighbours:
        cell: cell inner values, cell outer values
        :param field:
        :param n_el_facets:
        :param fc_n:
        :param velo:
        :param dofs: in shape (n_cell, n_el_nod, 1)
        :param nb_dofs: in shape (n_cell, n_el_facets, n_el_nod, 1)
        :return: (n_cell, n_el_facets, self.n_el_facets)
        """
        dim = fc_n.shape[-1]
        if dim == 1:
            facet_integrals = nm.zeros((self.n_cell, self.n_el_facets, 2, 1), dtype=nm.float64)
            facet_integrals[:, 0, 0] = dofs[:, 0] - dofs[:, 1]
            facet_integrals[:, 1, 0] = dofs[:, 0] + dofs[:, 1]
            facet_integrals[:, 0, 1] = nb_dofs[:, 0, 0] + nb_dofs[:, 0, 1]
            facet_integrals[:, 1, 1] = nb_dofs[:, 1, 0] - nb_dofs[:, 1, 1]

            facet_fluxs = nm.zeros((nm.shape(dofs)[0], n_el_facets, dim))
            for facet_n in range(n_el_facets):
                a = facet_integrals[:, facet_n, 0]
                b = facet_integrals[:, facet_n, 1]
                C = nm.abs(nm.sum(fc_n[:, facet_n, :] * velo, axis=1))[:, None]
                facet_fluxs[:, facet_n] = (velo * a + velo * b) / 2 + \
                                          C * fc_n[:, facet_n, :] * (a - b) / 2
            return facet_fluxs
        elif dim == 2:
            qp, ws = field.get_facet_qp(None)
            # TODO get basis values at qps
            # TODO get C
            # TODO compute fluxes as above


