import numpy as np
from typing import Union, List


class Array1d(type):

    @classmethod
    def __instancecheck__(cls, inst):
        if not isinstance(inst, np.ndarray):
            return False

        if inst.ndim != 1:
            return False

        return True


class Array2d(type):

    @classmethod
    def __instancecheck__(cls, inst):
        if not isinstance(inst, np.ndarray):
            return False

        if inst.ndim != 2:
            return False

        return True


Array = Union[Array2d, Array1d, List[float]]
