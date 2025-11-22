from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import types
import typing
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Union, get_args, get_origin

from typing_extensions import get_original_bases

from invariants.state import State, StateMachine


@dataclass
class Transition:
    source: type[State]
    target: type[State]
    event: str
    guard: str | dict[str, Any] | None = None


def get_root_state(machine_cls: type) -> type[State] | None:
    """Extract the generic parameter T from StateMachine[T]."""
    for base in get_original_bases(machine_cls):
        origin = get_origin(base)
        if origin is not None and issubclass(origin, StateMachine):
            args = get_args(base)
            if args and len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], State):
                return args[0]
    return None


def get_concrete_states(root_state: type[State]) -> list[type[State]]:
    """Get all concrete (non-Statefull) descendants of a root state."""
    result: list[type[State]] = []

    def walk(cls: type[State]) -> None:
        if cls is not root_state and not cls.has_statefull_fields():
            result.append(cls)
        for sub in cls.__subclasses__():
            walk(sub)

    walk(root_state)
    return result


def _unpack_union(annotation: Any) -> list[Any]:
    """Unpack Union or X | Y into a list of types."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return list(get_args(annotation))
    return [annotation]


def _is_state_subclass(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, State)


def extract_transitions(machine_cls: type) -> list[Transition] | None:
    """Extract transitions from the execute method's type hints.

    Returns None if the machine is a query (non-State return type)
    or has invalid signatures.
    """
    execute = getattr(machine_cls, "execute", None)
    if execute is None:
        return None

    try:
        hints = typing.get_type_hints(execute)
    except Exception:  # pragma: no cover
        return None

    params = list(inspect.signature(execute).parameters.keys())
    if len(params) < 2:
        return None

    input_annotation = hints.get(params[1])
    return_annotation = hints.get("return")

    if input_annotation is None or return_annotation is None:
        return None

    input_types = _unpack_union(input_annotation)
    output_types = _unpack_union(return_annotation)

    if not all(_is_state_subclass(t) for t in input_types):
        return None
    if not all(_is_state_subclass(t) for t in output_types):
        return None

    root_state = get_root_state(machine_cls)
    if root_state is not None:
        for t in input_types + output_types:
            if not issubclass(t, root_state):
                return None

    return [
        Transition(source=inp, target=out, event=machine_cls.__name__)
        for inp in input_types
        for out in output_types
    ]


@dataclass
class NestingRelation:
    parent_root: type[State]
    child_root: type[State]
    field_name: str
    allowed_children: dict[type[State], set[type[State]]]


def unwrap_state_types(annotation: Any) -> set[type[State]]:
    """Recursively unwrap a type annotation to find all State subclasses."""
    if _is_state_subclass(annotation):
        return {annotation}

    origin = get_origin(annotation)

    # Annotated[X, ...] → unwrap X
    if origin is typing.Annotated:
        args = get_args(annotation)
        if args:
            return unwrap_state_types(args[0])

    # Union / X | Y → unwrap each
    if origin is Union or origin is types.UnionType:
        result: set[type[State]] = set()
        for arg in get_args(annotation):
            result |= unwrap_state_types(arg)
        return result

    # tuple[X, ...] → unwrap X
    if origin is tuple:
        args = get_args(annotation)
        if args:
            result = set()
            for arg in args:
                if arg is not Ellipsis:
                    result |= unwrap_state_types(arg)
            return result

    return set()


def find_state_root(state_types: set[type[State]]) -> type[State] | None:
    """Find the common root State for a set of concrete states."""
    if not state_types:
        return None

    def _get_root(cls: type) -> type[State] | None:
        for klass in cls.__mro__:
            if klass is State or klass is object:
                continue  # pragma: no cover
            if issubclass(klass, State) and State in klass.__bases__:
                return klass
        return None  # pragma: no cover

    roots = {_get_root(t) for t in state_types}
    roots.discard(None)
    if len(roots) == 1:
        return roots.pop()
    return None


def detect_nesting(
    parent_root: type[State],
    child_roots: set[type[State]],
) -> list[NestingRelation]:
    """Detect nesting relationships between parent and child state hierarchies."""
    concrete_parents = get_concrete_states(parent_root)
    # field_name → {parent_concrete → set of child states}
    field_groups: dict[str, dict[type[State], set[type[State]]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for parent_cls in concrete_parents:
        hints = typing.get_type_hints(parent_cls, include_extras=True)
        for field_name, annotation in hints.items():
            state_types = unwrap_state_types(annotation)
            if state_types:
                root = find_state_root(state_types)
                if root is not None and root in child_roots and root is not parent_root:
                    field_groups[field_name][parent_cls] = state_types

    result: list[NestingRelation] = []
    for field_name, parent_map in field_groups.items():
        if not parent_map:  # pragma: no cover
            continue
        # All should share the same child root
        all_types = set()
        for types_set in parent_map.values():
            all_types |= types_set
        child_root = find_state_root(all_types)
        if child_root is None:  # pragma: no cover
            continue
        result.append(NestingRelation(
            parent_root=parent_root,
            child_root=child_root,
            field_name=field_name,
            allowed_children=dict(parent_map),
        ))

    return result


def detect_all_nestings(machines: Sequence[type]) -> list[NestingRelation]:
    """Detect all nesting relationships from a list of machines."""
    roots: set[type[State]] = set()
    for m in machines:
        r = get_root_state(m)
        if r is not None:
            roots.add(r)

    result: list[NestingRelation] = []
    for root in roots:
        nestings = detect_nesting(root, roots)
        result.extend(nestings)
    return result



def extract_guard_name(
    state_cls: type[State],
    field_name: str,
) -> str | dict[str, Any] | None:
    """Generate a guard name from a state's nested field annotation.

    Rules:
    - ContainsOne(X) → "any{X.__name__}"
    - tuple[X, ...] (single) → "only{X.__name__}"
    - tuple[X | Y, ...] (union) → "only{X}Or{Y}"
    - Both ContainsOne + union → {"type": "and", "guards": [...]}
    """
    from invariants.conditions import ContainsOne

    hints = typing.get_type_hints(state_cls, include_extras=True)
    annotation = hints.get(field_name)
    if annotation is None:
        return None

    any_guard: str | None = None
    only_guard: str | None = None

    # Unwrap Annotated to get inner type and metadata
    inner = annotation
    if get_origin(annotation) is typing.Annotated:
        args = get_args(annotation)
        inner = args[0]
        for metadata in args[1:]:
            if isinstance(metadata, ContainsOne):
                any_guard = f"any{metadata.required_type.__name__}"

    # Unwrap tuple[X, ...] to get the item type
    if get_origin(inner) is tuple:
        tuple_args = get_args(inner)
        if tuple_args:
            item_type = tuple_args[0]
            origin = get_origin(item_type)
            if origin is Union or origin is types.UnionType:
                type_names = [t.__name__ for t in get_args(item_type) if _is_state_subclass(t)]
                if type_names:
                    only_guard = "only" + "Or".join(type_names)
            elif _is_state_subclass(item_type):
                only_guard = f"only{item_type.__name__}"

    if any_guard and only_guard:
        return {"type": "and", "guards": [any_guard, only_guard]}
    return any_guard or only_guard


def attach_guards(
    transitions: list[Transition],
    nestings: list[NestingRelation],
) -> list[Transition]:
    """Attach guards to transitions based on target state's nested field annotations."""
    result: list[Transition] = []
    for t in transitions:
        guard = None
        for nesting in nestings:
            if t.target in nesting.allowed_children:
                guard = extract_guard_name(t.target, nesting.field_name)
                break
        if guard is not None:
            result.append(Transition(source=t.source, target=t.target, event=t.event, guard=guard))
        else:
            result.append(t)
    return result



def _find_machines_in_module(module: types.ModuleType) -> list[type]:
    """Find all StateMachine subclasses defined in a module."""
    machines = []
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, StateMachine)
            and obj is not StateMachine
            and obj.__module__ == module.__name__
        ):
            machines.append(obj)
    return machines


def _get_imported_modules(module: types.ModuleType) -> list[types.ModuleType]:
    """Get all modules directly imported by the given module."""
    result: list[types.ModuleType] = []
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, types.ModuleType) and obj is not module:
            result.append(obj)
    # Also check for 'from X import Y' — scan sys.modules for modules
    # whose names appear as prefixes of imported State classes
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, State) and obj.__module__ != module.__name__:
            imported_mod = sys.modules.get(obj.__module__)
            if imported_mod is not None and imported_mod not in result:
                result.append(imported_mod)
    return result


def discover_machines(module: types.ModuleType) -> list[type]:
    """Find all StateMachine subclasses in a module and related imported modules.

    Scans the target module for machines, then checks imported modules for
    machines whose root states are referenced by the target module's state
    hierarchies (e.g., nested state fields).
    """
    machines = _find_machines_in_module(module)

    # Collect root states from the target module's machines
    local_roots: set[type[State]] = set()
    for m in machines:
        r = get_root_state(m)
        if r is not None:
            local_roots.add(r)

    # Find state types referenced in local concrete states' annotations
    referenced_roots: set[type[State]] = set()
    for root in local_roots:
        for concrete in get_concrete_states(root):
            hints = typing.get_type_hints(concrete, include_extras=True)
            for annotation in hints.values():
                state_types = unwrap_state_types(annotation)
                for st in state_types:
                    sr = find_state_root({st})
                    if sr is not None and sr not in local_roots:
                        referenced_roots.add(sr)

    if not referenced_roots:
        return machines

    # Scan imported modules for machines operating on referenced root states
    seen = {id(m) for m in machines}
    for imported_mod in _get_imported_modules(module):
        for m in _find_machines_in_module(imported_mod):
            if id(m) not in seen:
                r = get_root_state(m)
                if r is not None and r in referenced_roots:
                    machines.append(m)
                    seen.add(id(m))

    return machines


def _build_on_dict(
    state_cls: type[State],
    transitions: list[Transition],
) -> dict[str, Any]:
    """Build the 'on' dict for a state from its outgoing transitions."""
    on_dict: dict[str, Any] = {}
    for t in transitions:
        if t.source is state_cls:
            event_name = t.event
            if t.guard is not None:
                entry: dict[str, Any] = {"target": t.target.__name__, "guard": t.guard}
                if event_name in on_dict:
                    existing = on_dict[event_name]
                    if isinstance(existing, list):
                        existing.append(entry)
                    else:  # pragma: no cover
                        on_dict[event_name] = [existing, entry]
                else:
                    on_dict[event_name] = [entry]
            else:
                if event_name in on_dict:
                    existing = on_dict[event_name]
                    if isinstance(existing, list):
                        existing.append(t.target.__name__)
                    else:
                        on_dict[event_name] = [existing, t.target.__name__]
                else:
                    on_dict[event_name] = t.target.__name__
    return on_dict


def build_xstate_config(machines: Sequence[type]) -> dict[str, dict[str, Any]]:
    """Build xstate config dicts grouped by root state name."""
    groups: dict[type[State], list[Transition]] = defaultdict(list)

    for machine_cls in machines:
        root = get_root_state(machine_cls)
        if root is None:
            continue
        transitions = extract_transitions(machine_cls)
        if transitions is None:
            continue
        groups[root].extend(transitions)

    nestings = detect_all_nestings(machines)

    configs: dict[str, dict[str, Any]] = {}
    for root_state, transitions in groups.items():
        concrete = get_concrete_states(root_state)
        root_nestings = [n for n in nestings if n.parent_root is root_state]

        # Attach guards if this root has nested state fields
        if root_nestings:
            transitions = attach_guards(transitions, root_nestings)

        states_dict: dict[str, Any] = {}

        sources_with_outgoing: set[str] = set()
        for t in transitions:
            sources_with_outgoing.add(t.source.__name__)

        for state_cls in concrete:
            on_dict = _build_on_dict(state_cls, transitions)

            state_config: dict[str, Any] = {}
            if state_cls.__name__ not in sources_with_outgoing:
                state_config["type"] = "final"

            if on_dict:
                state_config["on"] = on_dict
            states_dict[state_cls.__name__] = state_config

        initial = concrete[0].__name__ if concrete else None
        config: dict[str, Any] = {
            "id": root_state.__name__,
            "states": states_dict,
        }
        if initial:
            config["initial"] = initial

        configs[root_state.__name__] = config

    return configs


def _render_guard(guard: str | dict[str, Any]) -> str:
    """Render a guard value as JS code (always a named string reference)."""
    if isinstance(guard, str):
        return f"'{guard}'"
    # Compound guards are registered by name in setup()
    return f"'{_compound_guard_name(guard)}'"


def _render_transition_object(item: dict[str, Any]) -> str:
    """Render a transition object like { target: 'X', guard: 'Y' }."""
    parts = [f"target: '{item['target']}'"]
    if "guard" in item:
        parts.append(f"guard: {_render_guard(item['guard'])}")
    return "{ " + ", ".join(parts) + " }"


def _render_state_config(state_name: str, state_config: dict[str, Any], indent: int) -> str:
    """Render a single state's xstate JS code."""
    pad = "  " * indent
    lines = [f"{pad}{state_name}: {{"]
    if state_config.get("type") == "final":
        lines.append(f"{pad}  type: 'final',")
    if "initial" in state_config:  # pragma: no cover
        lines.append(f"{pad}  initial: '{state_config['initial']}',")
    if "states" in state_config:  # pragma: no cover
        lines.append(f"{pad}  states: {{")
        for child_name, child_config in state_config["states"].items():
            lines.append(_render_state_config(child_name, child_config, indent + 2))
        lines.append(f"{pad}  }},")
    on_dict = state_config.get("on", {})
    if on_dict:
        lines.append(f"{pad}  on: {{")
        for event, target in on_dict.items():
            if isinstance(target, list):
                items: list[str] = []
                for item in target:
                    if isinstance(item, dict):
                        items.append(_render_transition_object(item))
                    else:  # pragma: no cover
                        items.append(f"'{item}'")
                lines.append(f"{pad}    {event}: [{', '.join(items)}],")
            else:
                lines.append(f"{pad}    {event}: '{target}',")
        lines.append(f"{pad}  }},")
    lines.append(f"{pad}}},")
    return "\n".join(lines)


def _compound_guard_name(guard: dict[str, Any]) -> str:
    """Generate a descriptive name for a compound guard."""
    parts = guard["guards"]
    return "And".join(parts)


def _collect_guard_info(config: dict[str, Any]) -> tuple[set[str], dict[str, dict[str, Any]], set[str]]:
    """Collect guard info from a config.

    Returns (simple_guard_names, compound_guards, guard_fns) where:
    - simple_guard_names: leaf guard strings
    - compound_guards: name → compound guard dict (for setup definition)
    - guard_fns: higher-level combinator names like 'and', 'or'
    """
    guard_names: set[str] = set()
    compound_guards: dict[str, dict[str, Any]] = {}
    guard_fns: set[str] = set()

    def _visit_guard(g: str | dict[str, Any]) -> None:
        if isinstance(g, str):
            guard_names.add(g)
        elif isinstance(g, dict) and "type" in g:
            guard_fns.add(g["type"])
            name = _compound_guard_name(g)
            compound_guards[name] = g
            for child in g.get("guards", []):
                _visit_guard(child)

    for state_config in config.get("states", {}).values():
        for target in state_config.get("on", {}).values():
            items = target if isinstance(target, list) else [target]
            for item in items:
                if isinstance(item, dict) and "guard" in item:
                    _visit_guard(item["guard"])

    return guard_names, compound_guards, guard_fns


def render_xstate_code(machines: Sequence[type]) -> str:
    """Generate xstate v5 JS code with setup() + createMachine() calls.

    The output can be pasted directly into stately.ai/viz.
    """
    configs = build_xstate_config(machines)

    # Collect all guard functions across all configs for the import
    all_guard_fns: set[str] = set()
    config_guards: dict[str, tuple[set[str], dict[str, dict[str, Any]], set[str]]] = {}
    has_any_guards = False
    for name, config in configs.items():
        guard_names, compound_guards, guard_fns = _collect_guard_info(config)
        config_guards[name] = (guard_names, compound_guards, guard_fns)
        all_guard_fns |= guard_fns
        if guard_names or compound_guards:
            has_any_guards = True

    imports = ["setup"] if has_any_guards else []
    imports.append("createMachine")
    imports.extend(sorted(all_guard_fns))
    parts: list[str] = [f"import {{ {', '.join(imports)} }} from 'xstate';", ""]

    for name, config in configs.items():
        var_name = name[0].lower() + name[1:]
        guard_names, compound_guards, _ = config_guards[name]

        if guard_names or compound_guards:
            # Use setup({ guards }).createMachine() pattern
            parts.append(f"const {var_name} = setup({{")
            parts.append("  guards: {")
            for gname in sorted(guard_names):
                parts.append(f"    {gname}: () => true,")
            for cname in sorted(compound_guards):
                cg = compound_guards[cname]
                guard_type = cg["type"]
                guards_list = ", ".join(f"'{g}'" for g in cg["guards"])
                parts.append(f"    {cname}: {guard_type}([{guards_list}]),")
            parts.append("  },")
            parts.append("}).createMachine({")
        else:
            parts.append(f"const {var_name} = createMachine({{")

        parts.append(f"  id: '{config['id']}',")
        if config.get("initial"):
            parts.append(f"  initial: '{config['initial']}',")
        parts.append("  states: {")
        for state_name, state_config in config["states"].items():
            parts.append(_render_state_config(state_name, state_config, indent=2))
        parts.append("  },")
        parts.append("});")
        parts.append("")

    return "\n".join(parts)


_XSTATE_VIZ_DIR_NAME = ".xstate-viz"


def _get_viz_dir() -> Path:  # pragma: no cover
    """Get the xstate-viz directory (git submodule in project root)."""
    return Path(__file__).resolve().parent.parent / _XSTATE_VIZ_DIR_NAME


def _ensure_xstate_viz() -> Path:  # pragma: no cover
    """Ensure xstate-display is cloned and has node_modules installed. Returns the path."""
    viz_dir = _get_viz_dir()

    if not viz_dir.exists() or not (viz_dir / "package.json").exists():
        import subprocess

        print("Cloning xstate-display ...")
        subprocess.run(
            ["git", "clone", "https://github.com/nkhitrov/xstate-display.git", str(viz_dir)],
            check=True,
        )

    if not (viz_dir / "node_modules").exists():
        import shutil
        import subprocess

        for cmd in ("yarn", "node"):
            if shutil.which(cmd) is None:
                print(f"Error: '{cmd}' is required but not found in PATH", file=sys.stderr)
                sys.exit(1)

        print("Installing xstate-viz dependencies (yarn install) ...")
        subprocess.run(
            ["yarn", "install", "--frozen-lockfile", "--ignore-engines"],
            cwd=viz_dir,
            check=True,
        )

    return viz_dir


def _build_ssr_url(xstate_code: str, port: int) -> str:  # pragma: no cover
    """Build the xstate-viz URL with ?ssr= param containing the machine code."""
    from urllib.parse import quote

    ssr_payload = {
        "data": {
            "id": "invariants",
            "text": xstate_code,
            "updatedAt": "2024-01-01T00:00:00Z",
            "youHaveLiked": False,
            "likesCount": 0,
            "project": {
                "id": "invariants",
                "name": "Invariants",
                "owner": {
                    "id": "invariants",
                    "displayName": "Invariants",
                    "avatarUrl": "",
                },
            },
        }
    }
    encoded = quote(json.dumps(ssr_payload))
    return f"http://localhost:{port}/viz/invariants?ssr={encoded}"


def _check_port_free(port: int) -> None:  # pragma: no cover
    """Exit with a clear error if the port is already in use."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            print(
                f"Error: port {port} is already in use. "
                f"Kill the existing process or use -p to pick another port.",
                file=sys.stderr,
            )
            sys.exit(1)


def serve(module_path: str, port: int = 3000) -> None:  # pragma: no cover
    """Start xstate-viz dev server with pre-filled machine code from a Python module."""
    import atexit
    import os
    import signal
    import socket
    import subprocess
    import time
    import webbrowser

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f"Error: module '{module_path}' not found", file=sys.stderr)
        sys.exit(1)

    machines = discover_machines(module)
    if not machines:
        print(f"No StateMachine subclasses found in '{module_path}'", file=sys.stderr)
        sys.exit(1)

    _check_port_free(port)

    xstate_code = render_xstate_code(machines)
    print(f"Found {len(machines)} machine(s): {', '.join(m.__name__ for m in machines)}")

    viz_dir = _ensure_xstate_viz()

    url = _build_ssr_url(xstate_code, port)

    env = {
        **os.environ,
        "PORT": str(port),
        "NODE_OPTIONS": "--openssl-legacy-provider",
    }
    print(f"Starting xstate-viz on http://localhost:{port} ...")

    proc = subprocess.Popen(
        ["npx", "next", "-p", str(port)],
        cwd=viz_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        # Create a new process group so we can kill the entire tree
        preexec_fn=os.setsid,
    )

    def _cleanup() -> None:
        """Kill the entire process group (node + children) on exit."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    atexit.register(_cleanup)

    # Ensure cleanup on SIGTERM/SIGHUP (atexit doesn't run for signals)
    def _signal_handler(signum: int, frame: Any) -> None:
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGHUP, _signal_handler)

    # Wait for the server to be ready, or detect early exit
    for _ in range(60):
        ret = proc.poll()
        if ret is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            print(f"Error: xstate-viz exited with code {ret}", file=sys.stderr)
            if stderr:
                print(stderr[:500], file=sys.stderr)
            sys.exit(1)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(1)
    else:
        print("Warning: server may not be ready yet, opening browser anyway")

    print("Opening browser...")
    webbrowser.open(url)
    print("Press Ctrl+C to stop")

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nStopping xstate-viz...")
        _cleanup()
        proc.wait(timeout=5)
        print("Stopped")


def print_code(module_path: str) -> None:  # pragma: no cover
    """Print xstate JS code to stdout."""
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f"Error: module '{module_path}' not found", file=sys.stderr)
        sys.exit(1)

    machines = discover_machines(module)
    if not machines:
        print(f"No StateMachine subclasses found in '{module_path}'", file=sys.stderr)
        sys.exit(1)

    print(render_xstate_code(machines))


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="XState tools for invariants state machines")
    subparsers = parser.add_subparsers(dest="command")

    print_parser = subparsers.add_parser("print", help="Print xstate JS code to stdout")
    print_parser.add_argument("module", help="Python module path to scan (e.g. examples.example)")

    serve_parser = subparsers.add_parser("serve", help="Start xstate-viz dev server")
    serve_parser.add_argument("module", help="Python module path to scan (e.g. examples.example)")
    serve_parser.add_argument("-p", "--port", type=int, default=3000, help="Dev server port (default: 3000)")

    args = parser.parse_args()
    if args.command == "print":
        print_code(args.module)
    elif args.command == "serve":
        serve(args.module, args.port)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
