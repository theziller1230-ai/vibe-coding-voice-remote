"""Qt transport for contract values - the marshalling layer between the
presentation view-models and QML.

Design facts proven empirically against PySide6 6.11 (and the reason this
module exists):

* QML cannot read attributes off arbitrary Python objects.  A raw
  ``contracts.py`` dataclass marshals to an opaque value (``row.title`` is
  ``undefined`` in JS), whether it arrives through ``Property(object)`` or a
  slot return.
* Slot return values cannot carry ``QObject`` instances at all
  (``result=object``: copy-convert error; ``result=QObject``/``QObject*``/
  the concrete class: crash; ``result="QVariant"``: null).
* The two mechanisms that DO work, and the only ones used here:

  1. **dict-subclass slot returns** - a ``dict`` subclass returned from a
     ``result="QVariantMap"`` slot becomes a real JS object (``result.ok``
     reads fine).  ``contract_qml_map`` therefore renders contract values as
     ``(Contract, dict)`` dual-storage subclasses: the result is BOTH a real
     contract instance (``isinstance(x, Validation)`` holds; fields, frozen
     semantics and equality work) and dict-compatible for the marshaller.
     No bare ``dict`` is ever created, stored or returned by this layer.
  2. **QObject mirrors for properties** - ``QObject`` instances with constant
     Properties work for single-object properties (``Property(QObject)``) and
     for list elements (``Property(list)`` -> ``modelData.title``).  So every
     contract-typed property (single or list) crosses as ``row_view`` mirrors
     whose Properties are named exactly like the contract fields.

Everything QML sees therefore carries exactly the camelCase field names
declared in ``contracts.py`` and nothing else - the contract shapes are the
only shapes that cross the ①/② boundary.
"""

from __future__ import annotations

import dataclasses
import typing
from typing import Any, Dict, List, Tuple, Type

from PySide6.QtCore import Property, QObject

from . import contracts

_QML_CONTRACT_TYPES: Dict[Type[Any], Type[Any]] = {}
_MIRROR_TYPES: Dict[Type[Any], Type[Any]] = {}


def _field_property_type(annotation: Any) -> type:
    """Map a contract field annotation to its Qt property scalar type."""

    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        annotation = typing.get_args(annotation)[0]
    if annotation is bool:
        return bool
    if annotation is int:
        return int
    return str


def _qml_contract_type(contract_cls: Type[Any]) -> Type[Any]:
    """Build (once per contract class) the dual-storage transport subclass.

    Instances are real ``contract_cls`` instances (the dataclass stores the
    fields) AND carry the same fields in dict storage, so PySide6's
    ``QVariantMap`` conversion renders them as JS objects with exactly the
    contract's field names.
    """

    cached = _QML_CONTRACT_TYPES.get(contract_cls)
    if cached is not None:
        return cached

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:
        contract_cls.__init__(self, *args, **kwargs)
        dict.__init__(
            self,
            {f.name: getattr(self, f.name) for f in dataclasses.fields(contract_cls)},
        )

    def __eq__(self: Any, other: Any) -> Any:
        if isinstance(other, contract_cls):
            return tuple(getattr(self, f.name) for f in dataclasses.fields(contract_cls)) == tuple(
                getattr(other, f.name) for f in dataclasses.fields(contract_cls)
            )
        return NotImplemented

    def __hash__(self: Any) -> int:
        return hash(
            (contract_cls.__qualname__,)
            + tuple(getattr(self, f.name) for f in dataclasses.fields(contract_cls))
        )

    qml_type = type(
        f"{contract_cls.__name__}Qml",
        (contract_cls, dict),
        {
            "__doc__": f"Qt-transport rendering of {contract_cls.__qualname__}.",
            "__init__": __init__,
            "__eq__": __eq__,
            "__hash__": __hash__,
        },
    )
    _QML_CONTRACT_TYPES[contract_cls] = qml_type
    return qml_type


def contract_qml_map(instance: Any) -> Any:
    """Render one contract instance for a ``result="QVariantMap"`` slot.

    The result is a real ``contracts`` instance (same class semantics) whose
    dict storage mirrors its own fields - never a bare ``dict``.
    """

    contract_cls = type(instance)
    return _qml_contract_type(contract_cls)(**dataclasses.asdict(instance))


def _mirror_type(contract_cls: Type[Any]) -> Type[QObject]:
    """Build (once per contract class) the read-only QObject mirror type."""

    cached = _MIRROR_TYPES.get(contract_cls)
    if cached is not None:
        return cached

    hints = typing.get_type_hints(contract_cls)
    namespace: Dict[str, Any] = {
        "__doc__": f"Read-only Qt mirror of {contract_cls.__qualname__}.",
        "__eq__": lambda self, other: self.contract
        == (getattr(other, "contract", other)),
        "__hash__": lambda self: hash(self.contract),
    }
    for field in dataclasses.fields(contract_cls):
        def _getter(self: Any, _name: str = field.name) -> Any:
            return getattr(self._contract, _name)

        namespace[field.name] = Property(
            _field_property_type(hints.get(field.name, str)), _getter, constant=True
        )
    mirror_type = type(f"{contract_cls.__name__}Row", (QObject,), namespace)
    _MIRROR_TYPES[contract_cls] = mirror_type
    return mirror_type


def row_view(instance: Any) -> QObject:
    """Wrap one contract instance as its QObject mirror (field-identical)."""

    mirror = _mirror_type(type(instance))()
    mirror._contract = instance
    mirror.contract = instance
    return mirror


def row_views(instances: typing.Iterable[Any]) -> List[QObject]:
    """Wrap a sequence of contract instances as QObject mirrors."""

    return [row_view(instance) for instance in instances]
