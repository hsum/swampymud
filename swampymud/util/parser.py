"""module for parser generator
The Grammar of Command Grammars:
(whitespace is ignored)
grammar = expression+
expression = '(' atom  ('|' atom )* ')' quantifer?
atom = identifier | keyword
quantifier = '?' | '*' | '+'
identifier = [A-Z]+
keyword = [A-Z]+


Technically speaking, parsing player input is *NOT* context free.
For instance, take the English sentence
"The old man the boat."
Often times, people read this as (The old man) [subject] (the boat) [object?].
This doesn't make sense, so people re-read it (searching for a verb).
(The old) [subject, using old as a substantive adjective] (man) [verb] (the boat) [object].

Let's use a more MUD-related example.
Say that you have an item ("treasure") protected by enemies (multiple "treasure guardian").
What does the following sentence evaluate to?
take treasure guardian
Does this mean take treasure (from) treasure guardian?
Or is the user just trying to take the treasure guardian (invalid).

This means that many of the typical parser-generator strategies don't
work here.

In the grammar of these paraser-generators, we note the following:
"objects" are phrases that should match in-game objects. They are indicated
in parentheses, with the type indicated all caps.
pickup (ITEM)
If more than one type is accepted, you can specify like so:
attack (ITEM | ENTITY)
You can provide multiple types (if desired):
attack (ITEM)

"keywords" are constant literal phrases. Most often, they are prepositions,
like the 'to' in the example below:
    give (ITEM) to (CHARACTER | ENTITY)

Parsing a list of tokens:
    work through the
"""
import re
from abc import ABC, abstractmethod
from copy import deepcopy
from enum import Enum
from collections import namedtuple


def split_args(string):
    """Split [string] on whitespace, respecting quotes.
    (Quotes are pruned in the process.)
    Examples:
        split_quotes('equip "epic sword"') -> ['equip', 'epic sword']
        split_quotes('say "oh no...    don\'t go!')) ->
            ['say', "oh no...    don't go!"]
    """
    in_quote = False # we will set this to ' or " as needed
    in_token = False # we are in the middle of a token (not whitespace)
    tokens = []
    # Note that reallocating strings is inefficient, so we store the
    # strings as lists and join them at the end.
    for char in string:
        if in_quote:
            if char == in_quote:
                # we are closing the quoted token
                in_quote = False
            else:
                # we are still inside a quoted token
                tokens[-1].append(char)
        elif char in "\"'":
            if in_token:
                # we're in a token (but not in a quoted token),
                # so go ahead and add this char
                tokens[-1].append(char)
            else:
                # we're making a new quoted token
                in_quote = char
                tokens.append([])
        # skip whitespace
        elif char in " \t\n\r":
            in_token = False
            continue
        else:
            # we're in a token
            if in_token:
                tokens[-1].append(char)
            # we just entered a new token
            else:
                tokens.append([char])
                in_token = True
    # TODO: should we catch if in_quote is still open?
    return ["".join(token) for token in tokens]


class ParseError(Exception):

    def __init__(self, args, **kwargs):
        # for now, simply take the failures and ignore rest of stack
        args = {stack[-1] for stack in args}
        super().__init__(args, **kwargs)


# annotation used for parsing grammar rules
Parsed = namedtuple("Parsed", ["rule", "tokens"])
# reason for a parse error failing
Fail = namedtuple("Fail", ["expected", "received"])

class Grammar(ABC):
    """Abstract Base Class for all other grammar expressions
    Grammar provide high-level abstractions for a provided grammar.
    """
    def __init__(self, expr):
        self.inner = expr

    @abstractmethod
    def to_nfa(self):
        """Return a Nondeterministic Finite Automaton representing
        this Grammar
        """
        pass

    # lazily create the NFA
    @property
    def nfa(self):
        if not hasattr(self, "_nfa"):
            self._nfa = self.to_nfa()
        return self._nfa

    def __repr__(self):
        """overriding repr()"""
        return f"{type(self).__name__}({self.inner!r})"

    def match(self, inp):
        return self.to_nfa().match(split_args(inp))

    def __eq__(self, other):
        """Overriding == for convenient unit testing"""
        return isinstance(other, type(self)) and other.inner == self.inner

    def matches(self, tokens):
        """Returns true if 'tokens' obey this rule."""
        return self.nfa.matches(tokens)

    def annotate(self, tokens):
        """Returns a list of all valid interpretations of this
        grammar.
        raises ParseError if no valid interpretation can be found.
        (This means that the returned list is guaranteed to have at
        least one valid intepretation.)
        """
        return self.nfa.annotate(tokens)

    @staticmethod
    def from_string(string):
        return _parse_grammar(string)


class Group(Grammar):
    """Implictly, a group functions as a stack within our stack"""
    def __init__(self, *args, alts=None):
        alts = [] if alts is None else alts
        self.alts = list(alts)
        self.args = list(args)

    def add(self, arg):
        self.args.append(arg)
        return self

    def quantify_last(self, Quantifier):
        if self.args:
            if not isinstance(self.args[-1], (Star, Plus, Optional)):
                self.args[-1] = Quantifier(self.args[-1])
            else:
                raise ValueError("Predicate already has quantifier")
        else:
            raise ValueError("Expected predicate before quantifier")

    def add_alternative(self):
        if not self.args:
            # if we haven't added anything, raise an error
            raise ValueError("empty alternative")
        self.alts.append(self.args)
        self.args = []

    def __repr__(self):
        if self.alts:
            if self.args:
                return f"Group({repr(self.args)[1:-1]}, alts={self.alts})"
            else:
                return f"Group(alts={self.alts})"
        else:
            return f"Group({repr(self.args)[1:-1]})"

    def __eq__(self, other):
        return isinstance(other, Group) and other.args == self.args and other.alts == self.alts

    def cleanup(self):
        """This operation detects
        1) any empty alternates
        2) empty group
        It also closed out the most recent alternative and adds it to
        the stack
        """
        if not self.args:
            if self.alts:
                # the most recent alternate is empty
                raise ValueError("empty alternate")
            else:
                # the entire group is empty
                raise ValueError("empty group")
        else:
            if self.alts:
                self.alts.append(self.args)
                self.args = []

    def to_nfa(self):
        if self.args:
            return NFA.concat(*map(lambda e: e.to_nfa(), self.args))
        else:
            return NFA.union(*map(
                lambda alt: NFA.concat(*map(lambda e: e.to_nfa(), alt)),
                self.alts
            ))


# two types of basic grammar expressions
class Keyword(Grammar):
    def __init__(self, keyword):
        self.inner = keyword

    def to_nfa(self):
        return NFA.emitter(NFA.match_on(self.inner), self)

# TODO: join union of Variables into one variable
# UPDATE: yes, this helps reduce the number of exponential options
class Variable(Grammar):
    def __init__(self, *types):
        self.inner = types

    def to_nfa(self):
        # this nfa matches one word exactly
        # however, variables can match an unlimited number of words
        return NFA.emitter(NFA.plus(NFA.match_on(Token.ANY)), self)


# three quantifiers
class Star(Grammar):
    """This Grammar rule represents the Kleene Star of the inner rule.
    https://en.wikipedia.org/wiki/Kleene_star
    """
    def __init__(self, expr):
        self.inner = expr

    def to_nfa(self):
        return NFA.star(self.inner.to_nfa())


class Plus(Grammar):
    """This Grammar rule represents the Kleene Plus of the inner rule.
    https://en.wikipedia.org/wiki/Kleene_star#Kleene_plus
    """
    def to_nfa(self):
        return NFA.plus(self.inner.to_nfa())


class Optional(Grammar):
    """This Grammar rule makes the inner operation optional."""

    def to_nfa(self):
        return NFA.optional(self.inner.to_nfa())


def _string_index(tok_index, tokens):
    """helper function for parse_grammar"""
    # compute the cumulative length of the list of tokens up to token [index]
    cumsum = []
    prev = 0
    for s in tokens[:tok_index]:
        length = len(s) if s else 0
        cumsum.append(length + prev)
        prev = length
    if cumsum:
        return cumsum[-1]
    # edge case: provided index is 0
    else:
        return 0


_grammar_token_re = re.compile(r"([()|*?+])|[ \t\r\n]")
def _parse_grammar(grammar: str) -> Grammar:
    """Returns a parser based on the provided grammar."""
    # actually, it just returns a DFA
    # parse grammar into tokens
    tokens = _grammar_token_re.split(grammar)

    # stack of grammar components
    stack = [Group()]

    for tok_index, token in enumerate(tokens):
        if not token:
            # token is empty string or None (whitespace)
            continue
        if token.islower():
            # it's a keyword
            stack[-1].add(Keyword(token))
        elif token.isupper():
            # do some kind of type checking here
            stack[-1].add(Variable(token))
        elif token == "(":
            # start new capturing group
            stack.append(Group())
        elif token == ")":
            # end previous capturing group / union
            finished_group = stack.pop()
            finished_group.cleanup()
            if stack:
                stack[-1].add(finished_group)
            else:
                index = _string_index(tok_index, tokens)
                raise ValueError(f"Unmatched ')' at index [{index}]")
        elif token == "|":
            stack[-1].add_alternative()
        # quantifiers
        elif token == "*":
            stack[-1].quantify_last(Star)
        elif token == "+":
            stack[-1].quantify_last(Plus)
        elif token == "?":
            stack[-1].quantify_last(Optional)
        else:
            index = _string_index(tok_index, tokens)
            raise ValueError(f"Unrecognized token {token!r} starting at index [{index}]")
    # do we have any unfinished capturing groups on the stack?
    if len(stack) > 1:
        count = len(stack) - 1
        index = _string_index(0, tokens)
        raise ValueError(f"Expected {count} ')', but input ended at [{index}]")
    stack[0].cleanup()
    return stack[0]


# Creating a few enums for simplicity
class Token(Enum):
    EPSILON = 0 # epsilon transition
    ANY = 1
    END = 2
    NOTHING = 3 # used in parse errors
    EMIT = 4 # internal value used in NFRs, do not use in token streams
    # do not mix up epsilon transitions with "nothing"

def _add_epsilon(from_state, to_index):
    """helper function that checks if a state can have an epsilon transition
    before adding to it"""
    # if any words are in from_state, we cannot add an epsilon
    for match in from_state:
        if match is not Token.EPSILON and match is not Token.EMIT:
            raise ValueError("Cannot add epsilon transition to state with matches")
    if Token.EPSILON not in from_state:
        from_state[Token.EPSILON] = []
    from_state[Token.EPSILON].append(to_index)


class NFA:
    """Class representing a nondeterministic finite automaton.
    I recommend using these static methods to build up your NFA from
    the bottom up:
        NFA.match_on() (for a basic matcher)
        NFA.star(), NFA.plus(), NFA.optional() (quantifiers)
        NFA.concat(), and NFA.union() (combining multiple rules)
        NFA.emitter() (for emitting signals when a rule is completed)

    Under the hood, we use a table to represent the states of the NFA.
    The first state (index 0) is always the beginning state.
    The last state (index len(table) - 1) is always the accepting state.
    Each state contains either epsilon transition to other states (a
    list of indices) or paths to other states given specific tokens (a
    dictionary).

    Much of the inspiration for this class comes from this blogpost from
    Denis Kyashif:
    https://deniskyashif.com/2019/02/17/implementing-a-regular-expression-engine/

    If you want to understand how this stage works, I highly recommend
    reading this blog post (maybe more than once).
    """
    def __init__(self, table=None):
        """Create an NFA based on the provided table.
        If no table is provided, a one-state NFA is created
        """
        if table is None:
            table = [{}]
        # the NFA is represented by a table
        # self._table[0] is always the beginning element,
        # and self._table[-1] is always the end (accepting) element
        self._table = table

    def __repr__(self):
        return f"NFA({self._table})"

    def copy(self):
        """Return a deep copy of this NFA"""
        return NFA(deepcopy(self._table))

    def _shift_table(self, shift_by: int):
        """Return a copy of table with all indices incremented"""
        new_table = []
        for state in self._table:
            # TODO: should regular match nodes be allowed to emit?
            new_state = {}
            if Token.EMIT in state:
                new_state[Token.EMIT] = state[Token.EMIT]
            if Token.EPSILON in state:
                shifted = [index + shift_by for index in state[Token.EPSILON]]
                new_state[Token.EPSILON] = shifted
            # if a state has epsilon transitions, then it only
            # has epsilon transitions
            else:
                for token, index in state.items():
                    if token is not Token.EMIT:
                        new_state[token] = index + shift_by
            new_table.append(new_state)
        return new_table

    def _concat_with(self, nxt):
        """Return a copy of this NFA joined to a copy of nxt"""
        table = deepcopy(self._table)
        nxt_table = nxt._shift_table(len(table))
        # index of nxt's start node will be length of this table
        _add_epsilon(table[-1], len(table))
        # update all of the indices in nxt
        table.extend(nxt_table)
        return NFA(table)

    @staticmethod
    def match_on(value):
        """Returns a simple NFA that matches on [value]"""
        table = [
            {value : 1}, # this is saying 'go to the next index'
            {} # since this is the last index, we win
        ]
        return NFA(table)

    @staticmethod
    def star(nfa):
        """Returns a NFA matching the Kleene Star of NFA"""
        # To implement the Klein Star operation, we simply
        # add a new state to the beginning and a new state to the end
        # This new state at the beginning can either transition to the
        # end or to the first node of the table.

        # shift one to account for new state at beginning
        shifted = nfa._shift_table(1)

        # old end can now loop to the beginning
        _add_epsilon(shifted[-1], 0)
        # add an epsilon transition to the end of the future table
        _add_epsilon(shifted[-1], len(shifted) + 1)

        new_start = {Token.EPSILON : [ 1, len(shifted) + 1]}
        new_end = {}

        table = [new_start] + shifted
        table.append(new_end)

        return NFA(table)

    @staticmethod
    def plus(nfa):
        """Returns a NFA matching the Kleene Plus of NFA"""
        # this could easily be implemented as NFA.concat(nfa, NFA.star(nfa))
        # word+ is equivalent to word word*
        # NFA.concat(nfa, NFA.closure(nfa))
        # however, we can save one epsilon state with this implementation
        # TODO: implement in the more optimal fashion above
        table = nfa.copy()._table

        # add an epsilon from the last state in the table to the beginning,
        # to allow for a loop after entering things
        _add_epsilon(table[-1], 0)
        _add_epsilon(table[-1], len(table))

        # add a new end
        table.append({})
        return NFA(table)

    @staticmethod
    def optional(nfa):
        # this approach is essentially the same as NFA.star, except
        # we do not add an epsilon transition from the old end to the new start

        # shift one to account for new state at beginning
        shifted = nfa._shift_table(1)
        # add an epsilon transition to the end of the future table
        _add_epsilon(shifted[-1], len(shifted) + 1)

        # new start can either push to the new NFA or bypass entirely
        new_start = { Token.EPSILON : [ 1, len(shifted) + 1]}
        new_end = {}

        table = [new_start] + shifted
        table.append(new_end)
        return NFA(table)

    @staticmethod
    def union(*nfas):
        # for optimization purposes, avoid
        if not nfas:
            return NFA()
        elif len(nfas) == 1:
            return nfas[0].copy()

        start = {Token.EPSILON : []}
        table = [start]
        old_ends = []

        for nfa in nfas:
            # add an epsilon to the start of this table
            # we do the 'unsafe' version here, since we know
            # start is a proper epsilon state
            start[Token.EPSILON].append(len(table))
            table.extend(nfa._shift_table(len(table)))
            # the new index of the old end of the table is the new length of the table
            old_ends.append(len(table) - 1)

        # add a new end
        new_end = len(table)
        table.append({})
        for end in old_ends:
            # we use the checked version here, because we need to check
            # if the ends are not epsilon states
            _add_epsilon(table[end], new_end)
        return NFA(table)

    @staticmethod
    def concat(*nfas):
        """concatentate several NFAs together
        note, passing in zero NFAs will produce a single state
        that is already accepting
        """

        # If no NFAs provided, return an empty NFA (matches exactly nothing).
        # We do this to avoid excess states
        if not nfas:
            return NFA()
        # Get the first NFA's table
        table = deepcopy(nfas[0]._table)
        # start concatenating!
        for nxt_nfa in nfas[1:]:
            # this is similar to NFA._concat_with
            nxt_table = nxt_nfa._shift_table(len(table))
            _add_epsilon(table[-1], len(table))
            table.extend(nxt_table)
        return NFA(table)

    @staticmethod
    def emitter(nfa: 'NFA', rule: Grammar) -> 'NFA':
        """Return a copy of [nfa] that emits a rule on completion.
        We use this when we want to build NFAs that actually parse input
        instead of just returning 'True' or 'False' if it matches.
        """
        # check that the provided value is a Grammar
        if not isinstance(rule, Grammar):
            raise ValueError("Error. Expected Grammar for rule, got "
                             f"'{type(rule)}'")

        table = nfa.copy()._table
        emit_state = {
            Token.EMIT: rule
        }
        # point the old last state to the new emitting state
        _add_epsilon(table[-1], len(table))
        # add the state to the table
        table.append(emit_state)

        return NFA(table)

    def transition(self, state_index, token):
        """Iterate over the states produced by the current state
        [state_index] with [token] as input.
        Any epsilon transitions are crawled through until reaching
        a non-epsilon transition.
        """
        state = self._table[state_index]
        if Token.EPSILON in state:
            for next_state in state[Token.EPSILON]:
                yield from self.transition(next_state, token)
        else:
            if state_index == len(self._table) - 1:
                # edge case, we already reached the end, but we're
                # pushing through the rest of the epsilons
                # so, just re-yield the state_index
                if token is Token.END:
                    yield state_index
            elif Token.ANY in state and token is not Token.END:
                yield state[Token.ANY]
            elif token in state:
                yield state[token]

    def trans_emit(self, state_index, token, emits=()):
        state = self._table[state_index]
        if Token.EMIT in state:
            emits = emits + (state[Token.EMIT],)
        if Token.EPSILON in state:
            for next_state in state[Token.EPSILON]:
                yield from self.trans_emit(next_state, token, emits)
        else:
            if state_index == len(self._table) - 1:
                # edge case, we already reached the end, but we're
                # pushing through the rest of the epsilons
                # so, just re-yield the state_index
                if token is Token.END:
                    yield (emits, state_index)
            elif Token.ANY in state and token is not Token.END:
                yield (emits, state[Token.ANY])
            elif token in state:
                yield (emits, state[token])

    def trans_expected(self, state_index, token):
        """Iterate over the states that FAIL to produce a new state in
        response to tokens. This method produces a reason for each
        failure.
        """
        # follow the same approach as transition
        state = self._table[state_index]
        if Token.EPSILON in state:
            for next_state in state[Token.EPSILON]:
                yield from self.trans_expected(next_state, token)
        else:
            if state_index == len(self._table) - 1:
                # received an extra token at the end
                if token is not Token.END:
                    yield Token.NOTHING
            else:
                if token is Token.END:
                    # get all the possible tokens
                    expected = tuple(state)
                    yield from expected
                elif not (token in state or Token.ANY in state):
                    expected = tuple(state)
                    yield from expected

    def matches(self, tokens):
        # add Token.END to the list of tokens, this helps
        # push through any states that are still epsilons
        tokens = tokens + [Token.END]

        # we can use a set because we don't really care about the paths
        states = {0}

        for token in tokens:
            next_states = set()
            for state in states:
                next_states.update(self.transition(state, token))
            states = next_states
        # did we reach the final state?
        return (len(self._table) - 1) in states

    def annotate(self, tokens):
        """Produce a list of all possible annotations for this
        NFA on Grammar emissions.
        raises ParseError if no valid interpretation can be found.
        (This means that the returned list is guaranteed to have at
        least one valid intepretation.)
        """
        tokens = tokens + [Token.END]

        states = [0]
        stacks = [[]]

        for token in tokens:
            next_states = []
            next_stacks = []
            for (state, stack) in zip(states, stacks):
                for (emits, next_state) in self.trans_emit(state, token):
                    next_states.append(next_state)
                    if emits:
                        # if you ever want nested grammar rules, modify
                        # this part
                        # until then, it's a safe assumption that one token =
                        # one grammar
                        rule, = emits

                        new_stack = stack.copy()

                        claimed = []
                        # start poppin off the stack until we reach a rule
                        while new_stack and isinstance(new_stack[-1], str):
                            claimed.append(new_stack.pop())
                        # group the rule and preceding tokens
                        new_stack.append(Parsed(rule, claimed[::-1]))

                        # add the new token to it for next round
                        new_stack.append(token)
                        next_stacks.append(new_stack)
                    else:
                        next_stacks.append(stack + [token])

            # if we ran out of states, we need to give an explanation
            if not next_states:
                failures = []
                for (state, stack) in zip(states, stacks):
                    # gather all the things that we could have expected
                    # using a set to remove duplicates
                    expected = tuple(set(self.trans_expected(state, token)))
                    failures.append(stack + [Fail(expected, received=token)])
                raise ParseError(failures)

            states = next_states
            stacks = next_stacks

        # if stacks have survived Token.END, then they are good
        return stacks
