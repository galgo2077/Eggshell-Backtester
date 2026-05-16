import os
import sys
import importlib

STRATEGY_REGISTRY = {}
STRATEGY_CLASSES = {}

def _discover():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    submodule_path = os.path.join(base_dir, "Strategies-eggshell")
    if submodule_path not in sys.path:
        sys.path.insert(0, submodule_path)

    for search_dir, is_submodule in [(base_dir, False), (submodule_path, True)]:
        if not os.path.isdir(search_dir):
            continue
        for entry in sorted(os.listdir(search_dir)):
            pkg_path = os.path.join(search_dir, entry)
            if not os.path.isdir(pkg_path):
                continue
            if entry.startswith("_") or entry.startswith("."):
                continue
            if not all(os.path.isfile(os.path.join(pkg_path, f)) for f in ["__init__.py", "strategy.py", "constants.py"]):
                continue

            try:
                if is_submodule:
                    mod = importlib.import_module(entry)
                else:
                    mod = importlib.import_module(f"strategies.{entry}")
                STRATEGY_REGISTRY[entry] = mod
                sys.modules[f"strategies.{entry}"] = mod

                const = getattr(mod, "constants", None)
                strategy_name = getattr(const, "STRATEGY_NAME", entry.upper())
                for attr in vars(mod).values():
                    if isinstance(attr, type) and attr.__name__.endswith("Strategy"):
                        STRATEGY_CLASSES[strategy_name] = attr
                        break
            except Exception as e:
                import sys as _sys
                print(f"[strategies] Failed to load '{entry}': {e}", file=_sys.stderr)

_discover()
