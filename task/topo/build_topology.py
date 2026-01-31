from .kg_loader import infer_category


def augment_snapshot(snapshot, kg_store):
    for comp in snapshot.get("components", []):
        part_id = comp.get("part_id", "")
        ref = comp.get("ref", "")
        comp["category"] = infer_category(part_id, ref=ref, kg_store=kg_store)
        pin_roles = kg_store.get_pin_roles(part_id) if kg_store else {}

        for pin in comp.get("pins", []):
            pin_id = str(pin.get("pin_id", ""))
            pin_name = str(pin.get("pin_name", ""))
            role = None
            if pin_id in pin_roles:
                role = pin_roles[pin_id]
            elif pin_name in pin_roles:
                role = pin_roles[pin_name]
            pin["pin_role"] = role

    for net in snapshot.get("nets", []):
        for ep in net.get("endpoints", []):
            # Fill pin_role from component pin data if present
            ref = ep.get("ref")
            pin_id = str(ep.get("pin_id", ""))
            pin_name = str(ep.get("pin_name", ""))
            role = _lookup_pin_role(snapshot, ref, pin_id, pin_name)
            ep["pin_role"] = role
            ep["component_category"] = _lookup_component_category(snapshot, ref)

    return snapshot


def _lookup_pin_role(snapshot, ref, pin_id, pin_name):
    for comp in snapshot.get("components", []):
        if comp.get("ref") != ref:
            continue
        for pin in comp.get("pins", []):
            if str(pin.get("pin_id", "")) == pin_id and str(pin.get("pin_name", "")) == pin_name:
                return pin.get("pin_role")
            if str(pin.get("pin_id", "")) == pin_id:
                return pin.get("pin_role")
            if str(pin.get("pin_name", "")) == pin_name:
                return pin.get("pin_role")
    return None


def _lookup_component_category(snapshot, ref):
    for comp in snapshot.get("components", []):
        if comp.get("ref") == ref:
            return comp.get("category")
    return None


def index_snapshot(snapshot):
    comps = {c.get("ref"): c for c in snapshot.get("components", [])}
    nets = {n.get("name"): n for n in snapshot.get("nets", [])}
    return {"components": comps, "nets": nets}
