import json
import os


def _load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _normalize_part_id(part_id):
    if not part_id:
        return ""
    return str(part_id).strip()


class KGStore:
    def __init__(self, base_dir=".."):
        self.base_dir = base_dir
        self.component_map = {}
        self.kg_component_map = {}
        self._load_all()

    def _load_all(self):
        component_path = os.path.join(self.base_dir, "component.json")
        kg_component_path = os.path.join(self.base_dir, "kg_component.json")

        if os.path.exists(component_path):
            data = _load_json(component_path)
            self.component_map = {c["id"]: c for c in data.get("components", [])}
        else:
            self.component_map = {}

        if os.path.exists(kg_component_path):
            data = _load_json(kg_component_path)
            self.kg_component_map = {c["id"]: c for c in data.get("components", [])}
        else:
            self.kg_component_map = {}

    def get_component(self, part_id):
        part_id = _normalize_part_id(part_id)
        if part_id in self.kg_component_map:
            return self.kg_component_map[part_id]
        return None

    def get_component_info(self, part_id):
        part_id = _normalize_part_id(part_id)
        if part_id in self.component_map:
            return self.component_map[part_id]
        return None

    def get_category(self, part_id):
        comp = self.get_component(part_id)
        if comp and comp.get("category"):
            return comp.get("category")
        comp_info = self.get_component_info(part_id)
        if comp_info and comp_info.get("category"):
            return comp_info.get("category")
        return None

    def get_pin_roles(self, part_id):
        comp = self.get_component(part_id)
        if comp and comp.get("pin_roles"):
            return comp.get("pin_roles")
        return {}

    def get_constraints(self, part_id):
        comp = self.get_component(part_id)
        if comp and comp.get("generic_constraints"):
            return comp.get("generic_constraints")
        return []

    def has_component(self, part_id):
        part_id = _normalize_part_id(part_id)
        return part_id in self.component_map or part_id in self.kg_component_map


def infer_category(part_id, ref=None, kg_store=None):
    part_id = _normalize_part_id(part_id)
    if kg_store:
        category = kg_store.get_category(part_id)
        if category:
            return category

    ref_prefix = (ref or "").strip()[:1].upper()
    if part_id in ("R", "C", "L", "D"):
        return "passive"
    if ref_prefix in ("R", "C", "L", "D"):
        return "passive"
    if "MOSFET" in part_id.upper() or ref_prefix == "Q":
        return "MOSFET"
    return "unknown"
