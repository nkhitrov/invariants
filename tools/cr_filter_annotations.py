"""A filter that skips mutations inside type annotations.

Type annotations are not evaluated at runtime, so mutating them
produces false positives in mutation testing.

Usage:
    python tools/cr_filter_annotations.py mutation.sqlite
"""

import logging
import sys
from functools import lru_cache

from cosmic_ray.ast import get_ast_from_path
from cosmic_ray.tools.filters.filter_app import FilterApp
from cosmic_ray.work_item import WorkResult, WorkerOutcome

log = logging.getLogger()

_ANNOTATION_TYPES = {"annassign", "tfpdef"}


def _find_leaf_at_pos(node, pos):
    """Find the leaf node at a given (line, col) position."""
    if hasattr(node, "children"):
        for child in node.children:
            if child.start_pos <= pos < child.end_pos:
                return _find_leaf_at_pos(child, pos)
            # Exact match on end_pos for zero-width or boundary cases
            if child.start_pos == pos:
                return _find_leaf_at_pos(child, pos)
    return node


def _is_type_checking_block(node):
    """Check if node is an `if TYPE_CHECKING:` statement."""
    if node.type != "if_stmt":
        return False
    children = node.children
    # if_stmt: 'if' <condition> ':' <suite> ...
    return len(children) >= 2 and getattr(children[1], "value", None) == "TYPE_CHECKING"


def _is_in_annotation(node):
    """Check if node is inside a type annotation or TYPE_CHECKING block."""
    current = node.parent
    while current is not None:
        if current.type in _ANNOTATION_TYPES:
            return True
        # Return type annotation: node after '->' in funcdef
        if current.type == "funcdef":
            arrow = None
            colon = None
            for child in current.children:
                value = getattr(child, "value", None)
                if value == "->":
                    arrow = child
                elif value == ":" and arrow is not None:
                    colon = child
                    break
            if arrow is not None and colon is not None:
                if arrow.end_pos <= node.start_pos <= colon.start_pos:
                    return True
        # if TYPE_CHECKING: block — not evaluated at runtime
        if _is_type_checking_block(current):
            return True
        current = current.parent
    return False


class AnnotationFilter(FilterApp):
    """Skip mutations that fall inside type annotations."""

    def description(self):
        return __doc__

    def filter(self, work_db, _args):
        @lru_cache
        def get_ast(module_path):
            return get_ast_from_path(module_path)

        skipped = 0
        total = 0

        for item in work_db.pending_work_items:
            total += 1
            for mutation in item.mutations:
                try:
                    ast = get_ast(mutation.module_path)
                except Exception:
                    log.warning("Failed to parse %s, skipping", mutation.module_path)
                    continue

                leaf = _find_leaf_at_pos(ast, mutation.start_pos)
                if _is_in_annotation(leaf):
                    log.info(
                        "annotation skipping %s %s %s %s",
                        item.job_id,
                        mutation.operator_name,
                        mutation.module_path,
                        mutation.start_pos,
                    )
                    work_db.set_result(
                        item.job_id,
                        WorkResult(
                            output="Filtered: inside type annotation",
                            worker_outcome=WorkerOutcome.SKIPPED,
                        ),
                    )
                    skipped += 1
                    break

        print(f"Annotation filter: skipped {skipped}/{total} pending mutations")


def main(argv=None):
    return AnnotationFilter().main(argv)


if __name__ == "__main__":
    sys.exit(main())
