"""
Normalizes structured data (JSON-LD and Microdata) into a consistent
typed object format using a Protocol-based Strategy pattern.
"""
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from webstore_sleuth.utils.converters import ensure_list


@dataclass(frozen=True)
class SchemaEntity:
    """
    Standardized return type for extracted schema entities.
    
    Attributes:
        types: A list of normalized schema type strings (e.g., ['product']).
        properties: The dictionary containing the entity's attributes.
    """
    types: list[str]
    properties: dict[str, Any] = field(default_factory=dict)


def _normalize_type_strings(t: Any) -> list[str]:
    """
    Parses and standardizes schema type definitions into a flat list of strings.
    """
    raw = ensure_list(t)
    out: list[str] = []

    for item in raw:
        if isinstance(item, str) and item.strip():
            # Isolates the class name from URLs and fragment identifiers
            token = item.strip().replace("#", "/").rsplit("/", 1)[-1]
            out.append(token.lower())

    return out


@runtime_checkable
class ExtractionStrategy(Protocol):
    """
    Interface defining the contract for data extraction strategies.
    Must return strongly-typed SchemaEntity objects.
    """
    def extract(self, data: dict[str, Any]) -> Iterable[SchemaEntity]:
        ...


class JsonLdStrategy:
    """
    Strategy that identifies and extracts JSON-LD nodes as SchemaEntity objects.
    """
    def extract(self, data: dict[str, Any]) -> Iterable[SchemaEntity]:
        candidates: list[SchemaEntity] = []
        raw_nodes = ensure_list(data.get("json-ld"))
        
        for entry in raw_nodes:
            candidates.extend(self._extract_nodes(entry))
            
        return candidates

    def _extract_nodes(self, node: Any) -> Generator[SchemaEntity, None, None]:
        """
        Recursively walks the node tree. When a typed node is found, it is yielded
        as a SchemaEntity.
        """
        if isinstance(node, list):
            for item in node:
                yield from self._extract_nodes(item)

        elif isinstance(node, dict):
            # 1. Detection: Check for JSON-LD type definitions
            node_type = node.get("@type") or node.get("type")

            if node_type:
                # Separate the raw properties from the normalized type
                normalized_types = _normalize_type_strings(node_type)
                
                # We create a copy of properties to avoid mutation, 
                # effectively stripping the definition of 'type' from the payload 
                # if desired, or keeping it for reference. Here we keep the raw node.
                yield SchemaEntity(
                    types=normalized_types, 
                    properties=node.copy()
                )

            # 2. Recursion: Deep search for nested entities in values
            for value in node.values():
                yield from self._extract_nodes(value)


class MicrodataStrategy:
    """
    Strategy that processes Microdata into SchemaEntity objects.
    Nested Microdata items are also converted to SchemaEntity instances within the properties.
    """
    def extract(self, data: dict[str, Any]) -> Iterable[SchemaEntity]:
        candidates: list[SchemaEntity] = []
        raw_nodes = ensure_list(data.get("microdata"))

        for item in raw_nodes:
            if isinstance(item, dict):
                entity = self._normalize_item(item)
                # Ensure the result is actually an entity (it might be raw data if no type found)
                if isinstance(entity, SchemaEntity):
                    candidates.append(entity)
        
        return candidates

    def _normalize_item(self, item: dict[str, Any]) -> SchemaEntity | dict[str, Any]:
        """
        Converts a raw Microdata dictionary into a SchemaEntity.
        """
        # Extract and normalize the type
        raw_type = item.get("type")
        normalized_types = _normalize_type_strings(raw_type)

        # Process properties
        normalized_props: dict[str, Any] = {}
        properties = item.get("properties", {})
        
        if isinstance(properties, dict):
            for key, val in properties.items():
                normalized_props[key] = self._convert_value(val)

        # If it has a type, it's a SchemaEntity. Otherwise, it's just a dict wrapper.
        # (Microdata items usually have types, but we handle the edge case).
        return SchemaEntity(types=normalized_types, properties=normalized_props)

    def _convert_value(self, val: Any) -> Any:
        """
        Recursively processes values. If a nested item is found, it is converted 
        to a SchemaEntity, allowing for deep object traversal.
        """
        if isinstance(val, list):
            return [self._convert_value(v) for v in val]

        if isinstance(val, dict):
            # Check if this dict represents a nested Microdata item
            if "properties" in val or "type" in val:
                return self._normalize_item(val)
            return val

        return val


class SchemaNormalizer:
    """
    Context class that executes extraction strategies and collects SchemaEntity results.
    """
    def __init__(self, strategies: list[ExtractionStrategy] = None):
        self.strategies = strategies or [JsonLdStrategy(), MicrodataStrategy()]

    def collect_candidates(self, data: dict[str, Any]) -> list[SchemaEntity]:
        """
        Aggregates normalized SchemaEntity objects from all strategies.
        """
        candidates: list[SchemaEntity] = []

        for strategy in self.strategies:
            candidates.extend(strategy.extract(data))

        return candidates