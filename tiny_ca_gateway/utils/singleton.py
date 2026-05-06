import abc
from typing import Any


class SingletonMeta(type):
    _instances = {}  # type: dict[Any, Any]

    def __call__(cls, *args, **kwargs) -> Any:  # type: ignore # pragma: no cover
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

    def reset_instance_force(cls) -> None:  # pragma: no cover
        if cls in cls._instances:
            del cls._instances[cls]

    def is_initialized(cls) -> bool:  # pragma: no cover
        return cls in cls._instances


class SingletonABCMeta(abc.ABCMeta, SingletonMeta):
    pass


class SingletonABC(metaclass=SingletonABCMeta):
    __slots__ = ()
