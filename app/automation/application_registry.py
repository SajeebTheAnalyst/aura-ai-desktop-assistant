from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationSpec:
    name: str
    command: tuple[str, ...]
    process_names: tuple[str, ...]
    aliases: tuple[str, ...] = ()


ALLOWED_APPLICATIONS = (
    ApplicationSpec("notepad", ("notepad.exe",), ("notepad.exe",), ("notepad app", "নোটপ্যাড")),
    ApplicationSpec("calculator", ("calc.exe",), ("calculatorapp.exe", "calc.exe"), ("calc", "ক্যালকুলেটর")),
    ApplicationSpec("paint", ("mspaint.exe",), ("mspaint.exe",), ("microsoft paint",)),
    ApplicationSpec("explorer", ("explorer.exe",), ("explorer.exe",), ("file explorer", "windows explorer")),
    ApplicationSpec("chrome", ("chrome.exe",), ("chrome.exe",), ("google chrome", "ক্রোম")),
    ApplicationSpec("edge", ("msedge.exe",), ("msedge.exe",), ("microsoft edge",)),
    ApplicationSpec("excel", ("excel.exe",), ("excel.exe",), ("microsoft excel",)),
)

_APPLICATIONS = {alias: spec for spec in ALLOWED_APPLICATIONS for alias in (spec.name, *spec.aliases)}


def resolve_application(name: str) -> ApplicationSpec | None:
    return _APPLICATIONS.get(" ".join(name.casefold().strip().split()))


def application_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in ALLOWED_APPLICATIONS)