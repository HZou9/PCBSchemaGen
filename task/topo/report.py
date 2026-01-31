
def format_errors(errors):
    if not errors:
        return ""
    lines = ["Topology verification failed:"]
    for err in errors:
        lines.append(f"- {err}")
    return "\n".join(lines)
