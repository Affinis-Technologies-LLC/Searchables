"""
Framework rules (ADR-024): what a framework provides without a declaration anywhere the index can
read, each rule named for what it stands in for. A link made by a rule is marked `via = 'rule'` so
the views can show it is not from a declaration.

The first rule: Spring Data repositories. A codebase interface that extends one of the framework's
repository interfaces inherits its CRUD members; when the framework's jar is not on disk (ADR-017
reads it when it is), this table supplies them, with their return types in terms of the entity.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

SPRING_DATA = "org.springframework.data"
CRUD = f"{SPRING_DATA}.repository.CrudRepository"
JPA = f"{SPRING_DATA}.jpa.repository.JpaRepository"
# Repository interfaces, by simple name, with their type parameters (entity, id)
REPOSITORIES = {name: ["T", "ID"] for name in (
    "Repository", "CrudRepository", "ListCrudRepository", "PagingAndSortingRepository", "ListPagingAndSortingRepository",
    "JpaRepository", "MongoRepository", "ReactiveCrudRepository", "CoroutineCrudRepository", "ElasticsearchRepository")}


@dataclass(frozen=True)
class Rule:
    declaring: str              # The framework type that declares the member, qualified
    name: str
    returns: str                # A class, "$T0" for the entity, "" for void or a primitive
    carried: str                # What the return type carries: "$T0" or ""
    kind: str = "method"
    params: int = -1
    language: str = "java"
    type_params: str = ""
    signature: str = ""

    def __getitem__(self, key: str):   # Read like a code_library row
        return getattr(self, key)


# Spring Data's CRUD members: what each returns in terms of the entity ($T0)
_SPRING_MEMBERS: Dict[str, Rule] = {}
for _name, _returns, _carried, _declaring in (
        ("save", "$T0", "", CRUD), ("saveAll", "java.lang.Iterable", "$T0", CRUD), ("findById", "java.util.Optional", "$T0", CRUD),
        ("existsById", "", "", CRUD), ("findAll", "java.lang.Iterable", "$T0", CRUD), ("findAllById", "java.lang.Iterable", "$T0", CRUD),
        ("count", "", "", CRUD), ("deleteById", "", "", CRUD), ("delete", "", "", CRUD), ("deleteAllById", "", "", CRUD),
        ("deleteAll", "", "", CRUD), ("flush", "", "", JPA), ("saveAndFlush", "$T0", "", JPA), ("saveAllAndFlush", "java.util.List", "$T0", JPA),
        ("deleteAllInBatch", "", "", JPA), ("deleteAllByIdInBatch", "", "", JPA), ("getReferenceById", "$T0", "", JPA),
        ("getById", "$T0", "", JPA), ("getOne", "$T0", "", JPA)):
    _SPRING_MEMBERS[_name] = Rule(_declaring, _name, _returns, _carried, signature=f"{_name}(…)")
for _name in ("findAll", "findAllById", "saveAll"):   # JpaRepository narrows these to List
    _SPRING_MEMBERS[_name] = Rule(JPA, _name, "java.util.List", "$T0", signature=f"List<T> {_name}(…)")


def is_repository(owner: str) -> bool:
    return owner.rsplit(".", 1)[-1] in REPOSITORIES and (owner.startswith(SPRING_DATA) or "." not in owner)


def type_params_of(owner: str) -> List[str]:
    return list(REPOSITORIES.get(owner.rsplit(".", 1)[-1], [])) if is_repository(owner) else []


def bindings_for(owner: str, arguments: Sequence[str], encode: Callable[[str], str]) -> Dict[str, str]:
    """The framework type's variables bound to the arguments written where the codebase extends it."""
    found = {}
    for param, argument in zip(type_params_of(owner), arguments):
        encoded = encode(argument)
        if encoded:
            found[param] = encoded
    return found


def member_of(owner: str, name: str) -> Optional[Rule]:
    """A member the framework gives a type that extends `owner`, when no declaration of it can be read."""
    if not is_repository(owner):
        return None
    return _SPRING_MEMBERS.get(name)
