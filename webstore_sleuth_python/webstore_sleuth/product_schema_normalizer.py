from typing import Any, Dict, List, Generator

from webstore_sleuth.utils.converters import ensure_list


class SchemaNormalizer:
    """
    Normalizer for structured data (JSON-LD & Microdata).
    """

    @staticmethod
    def _normalize_type_strings(t: Any) -> List[str]:
        """
        Extracts and normalizes Schema types.
        Handles: "https://schema.org/Product", "Product", ["Product", "Thing"]
        """
        raw = ensure_list(t)
        out: List[str] = []

        for item in raw:
            if isinstance(item, str) and item.strip():
                # Handle URLs (schema.org/Product) and Fragment IDs (#Product)
                # We use rsplit to efficiently grab the last segment
                token = item.strip().replace("#", "/").rsplit("/", 1)[-1]
                out.append(token.lower())

        return out

    @classmethod
    def _extract_jsonld_nodes(cls, node: Any) -> Generator[Dict[str, Any], None, None]:
        """
        Generic recursive generator. Walks the ENTIRE tree.
        Does not mutate the input; yields normalized copies of found entities.
        """
        if isinstance(node, list):
            for item in node:
                yield from cls._extract_jsonld_nodes(item)

        elif isinstance(node, dict):
            # 1. Detection: Is this a candidate?
            # We look for standard JSON-LD '@type' or loosely structured 'type'
            node_type = node.get("@type") or node.get("type")

            if node_type:
                # Return a shallow copy with normalized type to avoid mutation
                candidate = node.copy()
                candidate["@type"] = cls._normalize_type_strings(node_type)
                yield candidate

            # 2. Recursion: Visit ALL values, not just specific keys.
            # Entities can be hidden in 'offers', 'author', 'itemListElement', etc.
            for value in node.values():
                yield from cls._extract_jsonld_nodes(value)

    @classmethod
    def _normalize_microdata(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hoists 'properties' to the root and normalizes recursively.
        """
        # 1. Normalize the type of the current item
        normalized_item = {"@type": cls._normalize_type_strings(item.get("type"))}

        # 2. Extract properties, recursively normalizing nested values
        properties = item.get("properties", {})
        if isinstance(properties, dict):
            for key, val in properties.items():
                # Microdata values are often lists; typically we want the first value
                # unless strictly defined otherwise.
                normalized_item[key] = cls._convert_microdata_value(val)

        return normalized_item

    @classmethod
    def _convert_microdata_value(cls, val: Any) -> Any:
        """
        Recursively handles values that might be simple strings or nested objects.
        """
        if isinstance(val, list):
            # If list contains objects, process them. If strings, keep them.
            return [cls._convert_microdata_value(v) for v in val]

        if isinstance(val, dict):
            # If this dict looks like a Microdata node (has 'properties' or 'type'),
            # we normalize it fully.
            if "properties" in val or "type" in val:
                return cls._normalize_microdata(val)
            return val

        return val

    @classmethod
    def collect_candidates(cls, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Aggregates and flattens entities.
        """
        candidates: List[Dict[str, Any]] = []

        # 1. Handle JSON-LD
        # We use a generator to flatten the tree structure into a list
        for entry in ensure_list(data.get("json-ld")):
            candidates.extend(cls._extract_jsonld_nodes(entry))

        # 2. Handle Microdata
        for item in ensure_list(data.get("microdata")):
            if isinstance(item, dict):
                candidates.append(cls._normalize_microdata(item))

        return candidates
