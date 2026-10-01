"""In-memory fakes for the pymongo subset used by the stores.

`FakeCollection` supports the operations the stores actually use:
`insert_one`, `find_one` with equality filters, `update_one` with `$set`
and upsert, and `create_index`. `_id` values are 24-character hex strings,
so `bson.ObjectId` conversions in `SessionStore` keep working.
"""

from typing import Any


class FakeInsertOneResult:
    def __init__(self, inserted_id: str) -> None:
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.documents: dict[str, dict] = {}
        self.indexes: list[tuple[str, dict[str, Any]]] = []
        self._counter = 0

    def create_index(self, field: str, **kwargs: Any) -> None:
        self.indexes.append((field, dict(kwargs)))

    def insert_one(self, document: dict) -> FakeInsertOneResult:
        stored = dict(document)
        document_id = self._next_id()
        stored["_id"] = document_id
        self.documents[document_id] = stored
        return FakeInsertOneResult(document_id)

    def find_one(self, query: dict) -> dict | None:
        for document in self.documents.values():
            if _matches(document, query):
                return document
        return None

    def update_one(
        self,
        query: dict,
        update: dict,
        upsert: bool = False,
    ) -> FakeUpdateResult:
        document = self.find_one(query)
        if document is None:
            if not upsert:
                return FakeUpdateResult(0)
            document = {key: value for key, value in query.items()}
            document_id = self._next_id()
            document["_id"] = document_id
            self.documents[document_id] = document

        _apply_update(document, update)
        return FakeUpdateResult(1)

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self._counter:024x}"


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection(name)
        return self.collections[name]


def _matches(document: dict, query: dict) -> bool:
    for field, expected in query.items():
        actual = document.get(field)
        if field == "_id":
            if str(actual) != str(expected):
                return False
        elif actual != expected:
            return False
    return True


def _apply_update(document: dict, update: dict) -> None:
    for operator, fields in update.items():
        if operator != "$set":
            raise AssertionError(f"Unsupported update operator in fakes: {operator}")
        document.update(fields)
