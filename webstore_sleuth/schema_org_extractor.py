"""
Normalizes structured data (JSON-LD and Microdata) into a consistent
recursive SchemaEntity tree.

EXAMPLES:

    1. JSON-LD Input:
       {
           "@type": "Product",
           "name": "Super Widget",
           "offers": {
               "@type": "Offer",
               "price": "19.99"
           }
       }

       --> Becomes SchemaEntity:
       SchemaEntity(
           types=['product'],
           properties={
               'name': 'Super Widget',
               'offers': SchemaEntity(
                   types=['offer'],
                   properties={'price': '19.99'}
               )
           }
       )

    2. Microdata Input (where properties are nested):
       {
           "type": "http://schema.org/Product",
           "properties": {
               "name": "Super Widget",
               "offers": {
                    "type": "http://schema.org/Offer",
                    "properties": { "price": "19.99" }
               }
           }
       }

       --> Becomes the same SchemaEntity structure as above.
"""
from abc import ABC, abstractmethod
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from typing import Any

from webstore_sleuth.utils.converters import ensure_list


@dataclass(frozen=True)
class SchemaOrgEntity:
    """
    Standardized extracted Schema.org entity.

    Attributes:
        types: Normalized lower-case type names (e.g., ["product"]).
        properties: The payload containing values or nested SchemaEntities.
    """

    types: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


def _normalize_type_strings(t: Any) -> list[str]:
    """
    Parses and standardizes schema type definitions.

    Input:
        "https://schema.org/Product"
        OR ["Product", "http://schema.org/Thing"]

    Output:
        ["product"]
        OR ["product", "thing"]
    """
    raw = ensure_list(t)
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            token = item.strip().replace("#", "/").rsplit("/", 1)[-1]
            out.append(token.lower())
    return out


def _flatten_tree(item: Any) -> Generator[SchemaOrgEntity, None, None]:
    """
    Recursively walks an item. If it is (or contains) a SchemaEntity,
    yields the entity itself and recursively yields all entities
    nested within its properties.

    Input:
        SchemaEntity(types=['product'], properties={
            'offer': SchemaEntity(types=['offer'], ...)
        })

    Output (Yields):
        1. SchemaEntity(types=['product'], ...)
        2. SchemaEntity(types=['offer'], ...)
    """
    if isinstance(item, list):
        for x in item:
            yield from _flatten_tree(x)

    elif isinstance(item, SchemaOrgEntity):
        yield item
        for val in item.properties.values():
            yield from _flatten_tree(val)


class BaseExtractionStrategy(ABC):
    """
    Abstract base strategy for extracting Schema.org entities.
    :
    1. Gather raw nodes (strategy-specific).
    2. Build entity trees (strategy-specific).
    3. Flatten and yield all entities (shared).
    """

    def extract(self, data: dict[str, Any]) -> Iterable[SchemaOrgEntity]:
        """
        Main entry point for extracting entities from a data dictionary.

        Input:
            {"json-ld": [...], "microdata": [...]}

        Output:
            Iterable yielding flattened SchemaEntity objects.
        """
        # HOOK 1: Get the raw list of dictionaries to process
        raw_nodes = self._get_nodes(data)

        root_entities = []
        for item in raw_nodes:
            # HOOK 2: Transform raw dict -> SchemaEntity
            if isinstance(item, dict):
                entity = self._build_tree(item)
                if isinstance(entity, SchemaOrgEntity):
                    root_entities.append(entity)

        # Standard: Flatten everything so consumers don't miss nested items
        for entity in root_entities:
            yield from _flatten_tree(entity)

    @abstractmethod
    def _get_nodes(self, data: dict[str, Any]) -> list[Any]:
        """
        Return the list of raw dictionaries to process.

        Input:
            Full data dictionary (e.g., {"json-ld": ..., "microdata": ...})

        Output:
            List of specific nodes (e.g., the contents of the "json-ld" key).
        """
        pass

    @abstractmethod
    def _build_tree(self, item: Any) -> Any:
        """
        Parse a single item (dict, list, or primitive) into a SchemaEntity or value.

        Input:
            Raw dictionary: {"@type": "Thing", "name": "A"}

        Output:
            SchemaEntity(types=['thing'], properties={'name': 'A'})
        """
        pass


class JsonLdStrategy(BaseExtractionStrategy):
    """
    Converts JSON-LD trees into SchemaEntity trees.
    Handles standard JSON-LD hierarchies and @graph definitions.
    """

    def _get_nodes(self, data: dict[str, Any]) -> list[Any]:
        """
        Extracts JSON-LD nodes, unwrapping @graph if present.

        Input:
            {
                "json-ld": [
                    {
                        "@context": "...",
                        "@graph": [
                            {"@type": "Product", "name": "A"},
                            {"@type": "WebPage", "name": "B"}
                        ]
                    }
                ]
            }

        Output (Flattened list of nodes):
            [
                {"@type": "Product", "name": "A"},
                {"@type": "WebPage", "name": "B"}
            ]
        """
        raw = ensure_list(data.get("json-ld"))
        nodes = []
        for node in raw:
            # Expand @graph if present
            if isinstance(node, dict) and "@graph" in node:
                nodes.extend(ensure_list(node["@graph"]))
            else:
                nodes.append(node)
        return nodes

    def _build_tree(self, data: Any) -> Any:
        """
        Recursively transforms raw JSON-LD dicts into SchemaEntity objects.

        Input:
            {"@type": "Product", "name": "Widget"}

        Output:
            SchemaEntity(types=['product'], properties={'name': 'Widget'})
        """
        if isinstance(data, list):
            return [self._build_tree(x) for x in data]

        if isinstance(data, dict):
            raw_type = data.get("@type") or data.get("type")

            # If no type, it's just a dictionary property
            if not raw_type:
                return {k: self._build_tree(v) for k, v in data.items()}

            norm_types = _normalize_type_strings(raw_type)
            norm_props = {}

            for k, v in data.items():
                if k in ("@type", "type", "@context", "@id"):
                    continue
                norm_props[k] = self._build_tree(v)

            return SchemaOrgEntity(types=norm_types, properties=norm_props)

        return data


class MicrodataStrategy(BaseExtractionStrategy):
    """
    Converts Microdata structures into SchemaEntity trees.
    """

    def _get_nodes(self, data: dict[str, Any]) -> list[Any]:
        """
        Extracts raw Microdata nodes.
        Note that Microdata items wrap their attributes in a 'properties' dict.

        Input:
            {
                "microdata": [
                    {
                        "type": "http://schema.org/Product",
                        "properties": {
                            "name": "Widget",
                            "offers": {
                                "type": "http://schema.org/Offer",
                                "properties": {"price": "10"}
                            }
                        }
                    }
                ]
            }

        Output (List of raw microdata items):
            [
                {
                    "type": "http://schema.org/Product",
                    "properties": {
                        "name": "Widget",
                        "offers": { ... }
                    }
                }
            ]
        """
        return ensure_list(data.get("microdata"))

    def _build_tree(self, val: Any) -> Any:
        """
        Hoists 'properties' to the root and normalizes types.

        Input:
            {
                "type": "http://schema.org/Offer",
                "properties": {"price": "100"}
            }

        Output:
            SchemaEntity(types=['offer'], properties={'price': '100'})
        """
        if isinstance(val, list):
            return [self._build_tree(v) for v in val]

        if isinstance(val, dict):
            raw_type = val.get("type")
            raw_props = val.get("properties")

            # Heuristic: It's an entity if it has a type OR explicit properties
            if raw_type or raw_props is not None:
                norm_types = _normalize_type_strings(raw_type)
                norm_props = {}

                if isinstance(raw_props, dict):
                    for k, v in raw_props.items():
                        norm_props[k] = self._build_tree(v)

                return SchemaOrgEntity(types=norm_types, properties=norm_props)

            return {k: self._build_tree(v) for k, v in val.items()}

        return val


class SchemaOrgExtractor:
    """
    Facade for extracting and normalizing Schema.org (JSON-LD, Microdata)
    into a unified SchemaEntity format.
    """

    def __init__(self, strategies: list[BaseExtractionStrategy] | None = None):
        self.strategies = strategies or [JsonLdStrategy(), MicrodataStrategy()]

    def collect_candidates(self, data: dict[str, Any]) -> list[SchemaOrgEntity]:
        """
        Runs all configured strategies against the input data and aggregates results.

        Input:
            {
                "json-ld": [{"@type": "Product", ...}],
                "microdata": [{"type": "Offer", ...}]
            }

        Output:
            [
                SchemaEntity(types=['product'], ...),
                SchemaEntity(types=['offer'], ...)
            ]
        """
        candidates: list[SchemaOrgEntity] = []
        for strategy in self.strategies:
            try:
                candidates.extend(strategy.extract(data))
            except Exception:
                # Silently ignore failures in one strategy
                continue
        return candidates
