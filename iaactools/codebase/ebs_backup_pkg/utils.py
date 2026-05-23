from __future__ import annotations
import atexit, json, logging, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ----- time & fmt -----
def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run_id_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

def secs_since(t0: float) -> float:
    return round(time.time() - t0, 3)

def safe_name(s: str) -> str:
    s = (s or "").strip()
    return s.replace("/", "_").replace("\\", "_").replace("  ", " ")

# ----- config -----
def load_config_file(path: Optional[str]) -> Dict[str, Any]:
    if not path: return {}
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit(f"--config file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yml", ".yaml"):
        try:
            import yaml  # type: ignore
        except Exception:
            raise SystemExit("PyYAML is required for YAML configs. Install with: pip install pyyaml")
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise SystemExit("Config must be a mapping/object at the top level.")
    return data

# ----- logging -----
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": utc_iso(), "level": record.levelname, "msg": record.getMessage()}
        for k in ("step", "phase", "ctx"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)

class TextFormatter(logging.Formatter):
    def __init__(self, fmt: str): super().__init__(fmt)
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        parts = [base]
        if hasattr(record, "phase"): parts.append(f"phase={record.phase}")
        if hasattr(record, "step"): parts.append(f"step={record.step}")
        if hasattr(record, "ctx") and isinstance(record.ctx, dict) and record.ctx:
            try: parts.append(json.dumps(record.ctx, ensure_ascii=False))
            except Exception: parts.append(repr(record.ctx))
        return " | ".join(parts)

class JsonArrayFileHandler(logging.FileHandler):
    def __init__(self, filename: str, mode: str = "w", encoding: Optional[str] = "utf-8"):
        super().__init__(filename, mode=mode, encoding=encoding, delay=False)
        self._first = True
        self.stream.write("["); self.stream.flush()
        atexit.register(self._close_array)
    def emit(self, record: logging.LogRecord) -> None:
        try:
            js = self.format(record)
            if not self._first: self.stream.write(",\n")
            else: self._first = False
            self.stream.write(js); self.stream.flush()
        except Exception:
            self.handleError(record)
    def _close_array(self):
        try: self.stream.write("]\n"); self.stream.flush()
        except Exception: pass

class JsonArrayStreamHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream if stream is not None else sys.stdout)
        self._first = True
        self.stream.write("["); self.stream.flush()
        atexit.register(self._close_array)
    def emit(self, record: logging.LogRecord) -> None:
        try:
            js = self.format(record)
            if not self._first: self.stream.write(",\n")
            else: self._first = False
            self.stream.write(js); self.stream.flush()
        except Exception:
            self.handleError(record)
    def _close_array(self):
        try: self.stream.write("]\n"); self.stream.flush()
        except Exception: pass

def build_logger(name: str, log_file: Optional[str], json_mode: bool, json_array: bool, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    fmt = JsonFormatter() if json_mode else TextFormatter("[%(levelname)s] %(message)s")
    if log_file:
        p = Path(log_file); p.parent.mkdir(parents=True, exist_ok=True)
        handler = JsonArrayFileHandler(log_file, mode="w", encoding="utf-8") if (json_mode and json_array) \
                  else logging.FileHandler(log_file, mode="w", encoding="utf-8")
    else:
        handler = JsonArrayStreamHandler(sys.stdout) if (json_mode and json_array) \
                  else logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt); logger.addHandler(handler)
    return logger

def log_step(logger: logging.Logger, phase: str, step: str, **ctx):
    logger.info(f"{phase}:{step}", extra={"phase": phase, "step": step, "ctx": ctx})

def flatten_tags(tags_list: Optional[list]) -> Dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tags_list or [])}

# ---------------------------------------------------------------------------
# User confirmation utilities (ported from monolithic main.py)
# ---------------------------------------------------------------------------
import sys

def prompt_yes_no(logger, question: str, assume_yes: bool, non_interactive_abort_msg: str) -> bool:
    """Interactive yes/no prompt with structured logging support."""
    if assume_yes:
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="--yes supplied", Question=question)
        return True
    if not sys.stdin.isatty():
        log_step(logger, "PROMPT", "ABORT", Reason="Non-interactive stdin; supply --yes", Question=question)
        if non_interactive_abort_msg:
            print(non_interactive_abort_msg)
        return False
    try:
        ans = input(f"{question} [y/N]: ").strip().lower()
    except EOFError:
        ans = ""
    if ans in ("y", "yes"):
        log_step(logger, "PROMPT", "CONFIRMED", Answer=ans, Question=question)
        return True
    log_step(logger, "PROMPT", "CANCELLED", Answer=ans or "(empty)", Question=question)
    return False


def confirm_phase(args, logger, question: str, abort_reason: str):
    """
    Unified phase confirmation handler — used across all phases.
    """
    # Always skip prompt in preview or simulate modes
    if getattr(args, "preview", False) or getattr(args, "simulate", False):
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="preview/simulate")
        return

    ok = prompt_yes_no(
        logger,
        question,
        assume_yes=getattr(args, "yes", False),
        non_interactive_abort_msg="Refusing to continue without --yes in non-interactive mode.",
    )
    if not ok:
        raise SystemExit(abort_reason)

