from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
)
from collections import (
    defaultdict,
)

from ..parse.identifiers import (
    ArgumentItemIdentifier,
    ArgumentTypeIdentifier,
    ExceptionItemIdentifier,
    ReturnTypeIdentifier,
    YieldTypeIdentifier,
    Identifier,
    NoqaIdentifier,
)
from .base import (
    BaseDocstring,
    DocstringStyle,
    Sections,
)
from ..node import (
    CykNode,
)
from ..config import (
    Configuration,
    Strictness,
)
from ..parse.numpy import (
    parse,
)
from ..lex import (
    lex,
    condense,
)
from ..errors import (
    DarglintError,
)


class Docstring(BaseDocstring):

    def __init__(self, root, style=DocstringStyle.SPHINX, config=None):
        # type: (Union[CykNode, str], DocstringStyle, Optional[Configuration]) -> None  # noqa: E501
        """Create a new docstring from the AST.

        Args:
            root: The root of the AST, or the docstring
                (as a string.)  If it is a string, the
                string will be parsed.
            style: The docstring style.  Discarded, since this
                docstring always represents the Numpy style.
            config: The configuration parameters.  Passed to
                lex to change the number of spaces which count
                as an indentation.

        """
        if isinstance(root, CykNode):
            self.root = root  # type: Optional[CykNode]
        else:
            self.root = parse(condense(lex(root, config)))
        self._lookup = self._discover()

    def _discover(self):
        # type: () -> Dict[str, List[CykNode]]
        """Walk the tree, finding all non-terminal nodes.

        Returns:
            A lookup table for compound Nodes by their NodeType.

        """
        if not self.root:
            return dict()
        lookup = defaultdict(
            lambda: list()
        )  # type: Dict[str, List[CykNode]]
        for node in self.root.in_order_traverse():
            lookup[node.symbol].append(node)
            for annotation in node.annotations:
                if issubclass(annotation, Identifier):
                    lookup[annotation.key].append(node)
        return lookup

    def get_section(self, section):
        # type: (Sections) -> Optional[str]
        nodes = []  # type: Optional[List[CykNode]]

        # TODO: Add Receives section
        if section == Sections.SHORT_DESCRIPTION:
            nodes = self._lookup.get('short-description', None)
        elif section == Sections.LONG_DESCRIPTION:
            nodes = self._lookup.get('long-description', None)
        elif section == Sections.ARGUMENTS_SECTION:
            nodes = self._lookup.get('arguments-section', None)
            extra = self._lookup.get('other-arguments-section', None)
            if nodes:
                nodes.extend(extra or [])
            else:
                nodes = extra
        elif section == Sections.RAISES_SECTION:
            nodes = self._lookup.get('raises-section', None)
            extra = self._lookup.get('warns-section', None)
            if nodes:
                nodes.extend(extra or [])
            else:
                nodes = extra
        elif section == Sections.YIELDS_SECTION:
            nodes = self._lookup.get('yields-section', None)
        elif section == Sections.RETURNS_SECTION:
            nodes = self._lookup.get('returns-section', None)
        elif section == Sections.NOQAS:
            nodes = self._lookup.get('noqa', None)
        else:
            raise Exception(
                'Unsupported section type, {}'.format(section)
            )

        if not nodes:
            return None

        return_value = ''
        for node in nodes:
            return_value += '\n\n' + node.reconstruct_string()

        return return_value.strip() or None

    def _get_types_unsorted(self, section):
        # type: (Sections) -> Optional[Union[str, List[Optional[str]]]]
        if section == Sections.ARGUMENTS_SECTION:
            if 'arguments-section' not in self._lookup:
                return None
            return [
                ArgumentTypeIdentifier.extract(x)
                for x in self._lookup.get(ArgumentTypeIdentifier.key, [])
            ]
        else:
            raise Exception(
                'Section type {} does not have types, '.format(
                    section.name
                ) + 'or is not yet supported'
            )
        return None

    def get_types(self, section):
        # type: (Sections) -> Optional[Union[str, List[Optional[str]]]]
        if section == Sections.RETURNS_SECTION:
            return_type = self._lookup.get(ReturnTypeIdentifier.key, [])
            if len(return_type) == 0:
                return None
            elif len(return_type) == 1:
                return ReturnTypeIdentifier.extract(return_type[0])
            else:
                raise NotImplementedError(
                    'Multiple types should be combined into a Union'
                )
        elif section == Sections.YIELDS_SECTION:
            yield_type = self._lookup.get(YieldTypeIdentifier.key, [])
            if len(yield_type) == 0:
                return None
            elif len(yield_type) == 1:
                return YieldTypeIdentifier.extract(yield_type[0])
            else:
                raise NotImplementedError(
                    'Multiple types should be combined into a Union'
                )

        # Sort the types according to the sorted items section.
        # This ensures that the results are always in the same
        # order.
        items = self._get_items_unsorted(section)
        if not items:
            return None
        types = self._get_types_unsorted(section)
        if not types:
            return []

        # Handle the case when two arguments are listed in
        # one line (like "m, n: int").
        sorted_types = list()
        for arg, _type in sorted(zip(items, types)):
            for _ in arg.split(','):
                sorted_types.append(_type)
        return sorted_types

    def _get_items_unsorted(self, section):
        # type: (Sections) -> Optional[List[str]]
        if section == Sections.ARGUMENTS_SECTION:
            return [
                ArgumentItemIdentifier.extract(x)
                for x in self._lookup.get(ArgumentItemIdentifier.key, [])
            ] or None
        elif section == Sections.RAISES_SECTION:
            return sorted(
                ExceptionItemIdentifier.extract(x)
                for x in self._lookup.get(ExceptionItemIdentifier.key, [])
            ) or None
        else:
            raise Exception(
                'Section type {} does not have items, '.format(
                    section.name
                ) + 'or is not yet supported.'
            )
        return None

    def get_items(self, section):
        # type: (Sections) -> Optional[List[str]]
        items = self._get_items_unsorted(section)
        if not items:
            return None
        sorted_items = list()
        for item in sorted(items):
            sorted_items.extend([
                x.strip() for x in item.split(',')
            ])
        return sorted_items

    def get_noqas(self):
        # type: () -> Dict[str, List[str]]
        """Get a map of the errors ignored to their targets.

        Returns:
            A dictionary containing the errors to ignore as keys and
            a list of which targets to apply these exceptions to as
            the values.  A blank list implies a global noqa.

        """
        noqas = dict()
        for noqa in self._lookup[NoqaIdentifier.key]:
            noqas[NoqaIdentifier.extract(noqa) or '*'] = (
                NoqaIdentifier.extract_targets(noqa)
            )
        return noqas

    def get_line_numbers(self, node_type):
        # type: (str) -> Optional[Tuple[int, int]]
        """Get the line numbers for the first instance of the given section.

        Args:
            node_type: The NodeType which we want line numbers for.
                These should be unique instances. (I.e. they should be
                in the set of compound NodeTypes which only occur
                once in a docstring. For example, "Raises" and "Args".

        Returns:
            The line numbers for the first instance of the given node type.

        """
        nodes = self._lookup[node_type]
        if nodes:
            return nodes[0].line_numbers
        return None

    def get_line_numbers_for_value(self, node_type, value):
        # type: (str, str) -> Optional[Tuple[int, int]]
        """Get the line number for a node with the given value.

        Args:
            node_type: The compound node which should contain the
                node we are searching for.
            value: The value of the node.

        Returns:
            A list of line numbers for nodes which match the
            parameters.

        """
        nodes = self._lookup[node_type]
        for node in nodes:
            for child in node.walk():
                if child.value == value and child.line_numbers:
                    return child.line_numbers
        return None

    @property
    def ignore_all(self):
        # type: () -> bool
        """Return whether we should ignore everything in the docstring.

        This happens when there is a bare noqa in the docstring, or
        there is "noqa: *" in the docstring.

        Returns:
            True if we should ignore everything, otherwise false.

        """
        return False

    def get_style_errors(self):
        # type: () -> Iterable[Tuple[Callable, Tuple[int, int]]]
        """Get any style errors annotated on the tree.

        Yields:
            Instances of DarglintErrors for style issues.

        # noqa: I302

        """
        if not self.root:
            return
        for node in self.root.in_order_traverse():
            for annotation in node.annotations:
                if issubclass(annotation, DarglintError):
                    yield annotation, node.line_numbers

    def satisfies_strictness(self, strictness):
        # type: (Strictness) -> bool
        """Return true if the docstring has no more than the min strictness.

        Args:
            strictness: The minimum amount of strictness which should
                be present in the docstring.

        Returns:
            True if there is no more than the minimum amount of strictness.

        """
        sections = {
            section for section in Sections
            if self.get_section(section)
        }
        if strictness == Strictness.SHORT_DESCRIPTION:
            return sections == {Sections.SHORT_DESCRIPTION}
        elif strictness == Strictness.LONG_DESCRIPTION:
            return sections in [
                {Sections.SHORT_DESCRIPTION},
                # Shouldn't be possible, but if it is in the future, then
                # we should allow this.
                {Sections.LONG_DESCRIPTION},
                {Sections.SHORT_DESCRIPTION, Sections.LONG_DESCRIPTION},
            ]
        else:
            return False
