import json


def _pin_net_names(pin):
    nets = []
    if hasattr(pin, "nets") and pin.nets:
        nets = list(pin.nets)
    elif hasattr(pin, "net") and pin.net is not None:
        nets = [pin.net]

    net_names = []
    for net in nets:
        name = getattr(net, "name", None)
        if name is None:
            name = str(net)
        net_names.append(str(name))
    return net_names


def _part_id_from_part(part):
    for attr in ("name", "value", "part_num", "device", "id"):
        val = getattr(part, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return part.ref


def snapshot_from_circuit(circuit):
    nets_map = {}
    components = []

    for part in getattr(circuit, "parts", []):
        ref = getattr(part, "ref", "")
        part_id = _part_id_from_part(part)
        value = getattr(part, "value", None)
        comp_entry = {
            "ref": ref,
            "part_id": part_id,
            "value": str(value) if value is not None else None,
            "pins": [],
        }

        for pin in getattr(part, "pins", []):
            pin_id = getattr(pin, "num", None)
            pin_name = getattr(pin, "name", "")
            if pin_id is None:
                pin_id = pin_name
            pin_id = str(pin_id)
            pin_name = str(pin_name) if pin_name is not None else ""

            net_names = _pin_net_names(pin)
            if not net_names:
                comp_entry["pins"].append(
                    {"pin_id": pin_id, "pin_name": pin_name, "net": None}
                )
                continue

            for net_name in net_names:
                comp_entry["pins"].append(
                    {"pin_id": pin_id, "pin_name": pin_name, "net": net_name}
                )
                nets_map.setdefault(
                    net_name, {"name": net_name, "endpoints": []}
                )["endpoints"].append(
                    {
                        "ref": ref,
                        "pin_id": pin_id,
                        "pin_name": pin_name,
                    }
                )

        components.append(comp_entry)

    nets = list(nets_map.values())
    return {"components": components, "nets": nets}


def snapshot_from_default_circuit():
    import builtins

    circuit = getattr(builtins, "default_circuit", None)
    if circuit is None:
        raise RuntimeError("default_circuit not found in builtins")
    return snapshot_from_circuit(circuit)


def serialize_snapshot(snapshot):
    return json.dumps(snapshot, ensure_ascii=False)


def main():
    snapshot = snapshot_from_default_circuit()
    print(serialize_snapshot(snapshot))


if __name__ == "__main__":
    main()
