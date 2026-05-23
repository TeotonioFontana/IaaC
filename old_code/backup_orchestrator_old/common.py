def mode_label(arg1=None, simulate=None) -> str:
    """
    Accept either:
      - mode_label(args)                 # where args has .preview/.simulate
      - mode_label(preview_bool, simulate_bool)
    """
    if hasattr(arg1, "preview") and hasattr(arg1, "simulate"):
        preview = bool(getattr(arg1, "preview", False))
        simulate = bool(getattr(arg1, "simulate", False))
    else:
        preview = bool(arg1)
        simulate = bool(simulate)

    if preview:
        return "PREVIEW (no side effects)"
    if simulate:
        return "SIMULATE (read-only + dry-run where supported)"
    return "EXECUTE"
