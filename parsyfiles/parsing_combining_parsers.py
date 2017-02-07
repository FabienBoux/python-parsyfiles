import traceback
from io import StringIO, TextIOBase
from logging import Logger
from typing import Type, Dict, Any, List

from parsyfiles.converting_core import Converter, S, ConversionChain
from parsyfiles.filesystem_mapping import PersistedObject
from parsyfiles.parsing_core import AnyParser, T, _ParsingPlanElement, BaseParser, get_parsing_plan_log_str
from parsyfiles.type_inspection_tools import get_pretty_type_str
from parsyfiles.var_checker import check_var


class DelegatingParser(AnyParser[T]):
    """
    A parser that delegates all the parsing tasks to another implementation ; and therefore does not implement directly
    the corresponding methods.
    """
    def _parse_singlefile(self, desired_type: Type[T], file_path: str, encoding: str, logger: Logger,
                          *args, **kwargs) -> T:
        """
        Implementation of AnyParser API
        """
        raise Exception('This should never happen, since this parser relies on underlying parsers')

    def _get_parsing_plan_for_multifile_children(self, obj_on_fs: PersistedObject, desired_type: Type[Any],
                                                 logger: Logger) -> Dict[str, Any]:
        """
        Implementation of AnyParser API
        """
        raise Exception('This should never happen, since this parser relies on underlying parsers')

    def _parse_multifile(self, desired_type: Type[T], obj: PersistedObject,
                         parsing_plan_for_children: Dict[str, AnyParser._RecursiveParsingPlan],
                         logger: Logger, *args, **kwargs) -> T:
        """
        Implementation of AnyParser API
        """
        raise Exception('This should never happen, since this parser relies on underlying parsers')


def print_error_to_io_stream(err: Exception, io: TextIOBase, print_big_traceback : bool = True):
    if print_big_traceback:
        traceback.print_tb(err.__traceback__, file=io, limit=-3)
    else:
        traceback.print_tb(err.__traceback__, file=io, limit=-1)
    io.writelines('  ' + str(err.__class__.__name__) + ' : ' + str(err))


class CascadeError(Exception):
    """
    Raised whenever parsing fails
    """

    def __init__(self, contents):
        """
        We actually can't put more than 1 argument in the constructor, it creates a bug in Nose tests
        https://github.com/nose-devs/nose/issues/725
        That's why we have a helper static method create()

        :param contents:
        """
        super(CascadeError, self).__init__(contents)

    @staticmethod
    def create_for_parsing_plan_creation(origin_parser: AnyParser[T], parent_plan: AnyParser._RecursiveParsingPlan[T],
                                         caught: Dict[AnyParser[T], Exception]):
        """
        Helper method provided because we actually can't put that in the constructor, it creates a bug in Nose tests
        https://github.com/nose-devs/nose/issues/725

        :param origin_parser:
        :param parent_plan:
        :param caught:
        :return:
        """
        base_msg = 'Error while trying to build parsing plan to parse  ' + str(parent_plan.obj_on_fs_to_parse) \
                   + ' as a ' + get_pretty_type_str(parent_plan.obj_type) + ' with parser \'' \
                   + str(origin_parser) + '\'. \n Caught the following exceptions from the various parsers tried: \n'
        msg = StringIO()
        for parser, err in caught.items():
            msg.writelines('--------------- From ' + str(parser) + ' caught: \n')
            print_error_to_io_stream(err, msg)
            msg.write('\n')

        return CascadeError(base_msg + msg.getvalue())

    @staticmethod
    def create_for_execution(origin_parser: AnyParser[T], parent_plan: AnyParser._RecursiveParsingPlan[T],
                             caught_exec: Dict[AnyParser[T], Exception]):
        """
        Helper method provided because we actually can't put that in the constructor, it creates a bug in Nose tests
        https://github.com/nose-devs/nose/issues/725

        :param origin_parser:
        :param parent_plan:
        :param caught_exec:
        :return:
        """
        base_msg = 'Error while trying to execute parsing plan to parse  ' + str(parent_plan.obj_on_fs_to_parse) \
                   + ' as a ' + get_pretty_type_str(parent_plan.obj_type) + ' with parser \'' \
                   + str(origin_parser) + '\'. \n Caught the following exceptions from the various parsers tried: \n'
        msg = StringIO()
        for parser, err in caught_exec.items():
            msg.writelines('--------------- From ' + str(parser) + ' caught: \n')
            print_error_to_io_stream(err, msg)
            msg.write('\n')

        return CascadeError(base_msg + msg.getvalue())


class CascadingParser(DelegatingParser[T]):
    """
    Represents a cascade of parsers that are tried in order: the first parser is used, then if it fails the second is
    used, etc.
    """
    def __init__(self, parsers: List[AnyParser[T]] = None):
        """
        Constructor from an initial list of parsers
        :param parsers:
        """

        # init
        # explicitly dont use base constructor
        # super(CascadingParser, self).__init__(supported_types=set(), supported_exts=set())
        self.configured = False
        self._parsers_list = []

        if parsers is not None:
            check_var(parsers, var_types=list, var_name='parsers')
            for parser in parsers:
                self.add_parser_to_cascade(parser)

    def __str__(self):
        if len(self._parsers_list) > 0:
            # if hasattr(CascadingParser.active_mf_parsers, 'parser') \
            #         and CascadingParser.active_mf_parsers.parser is not None:
            #     return str(CascadingParser.active_mf_parsers.parser) + '(selected from a try/catch cascade of parsers)'
            # elif len(self._parsers_list) == 1:
            #     return str(self._parsers_list[0])
            # else:
                # return 'ParserCascade[Try \'' + str(self._parsers_list[0]) + (
                #     '\' then \'' if len(self._parsers_list) > 1 else '\'') \
                #        + '\' then \''.join([str(parser) for parser in self._parsers_list[1:]]) + ']'
            return '[Try \'' + str(self._parsers_list[0]) + '\' then \'' \
                   + '\' then \''.join([str(parser) for parser in self._parsers_list[1:]]) + ']'
        else:
            return 'ParserCascade[Empty]'

    def __repr__(self):
        # __repr__ is supposed to offer an unambiguous representation,
        # but pprint uses __repr__ so we'd like users to see the small and readable version
        return self.__str__()

    def add_parser_to_cascade(self, parser: AnyParser[T]):
        """
        Adds the provided parser to this cascade. If this is the first parser, it will configure the cascade according
        to the parser capabilities (single and multifile support, extensions).
        Subsequent parsers will have to support the same capabilities at least, to be added.

        :param parser:
        :return:
        """
        # the first parser added will configure the cascade
        if not self.configured:
            #self.supports_singlefile = parser.supports_singlefile
            self.supported_exts = parser.supported_exts
            self.supported_types = parser.supported_types
            #self.supports_multifile = parser.supports_multifile

        # check if new parser is compliant with previous ones
        if self.supports_singlefile():
            if not parser.supports_singlefile():
                raise ValueError(
                    'Cannot add this parser to this parsing cascade : it does not match the rest of the cascades '
                    'configuration (singlefile support)')

        if self.supports_multifile():
            if not parser.supports_multifile():
                raise ValueError(
                    'Cannot add this parser to this parsing cascade : it does not match the rest of the cascades '
                    'configuration (multifile support)')

        if Any not in parser.supported_types:
            if Any in self.supported_types:
                raise ValueError(
                    'Cannot add this parser to this parsing cascade : it does not match the rest of the cascades '
                    'configuration (the cascade supports any type while the parser only supports '
                    + str(parser.supported_types) + ')')
            else:
                missing_types = set(self.supported_types) - set(parser.supported_types)
                if len(missing_types) > 0:
                    raise ValueError(
                        'Cannot add this parser to this parsing chain : it does not match the rest of the chains '
                        'configuration (supported types should at least contain the supported types already in place.'
                        ' The parser misses type(s) ' + str(missing_types) + ')')

        missing_exts = set(self.supported_exts) - set(parser.supported_exts)
        if len(missing_exts) > 0:
            raise ValueError(
                'Cannot add this parser to this parsing chain : it does not match the rest of the chains '
                'configuration (supported extensions should at least contain the supported extensions already in '
                'place. The parser misses extension(s) ' + str(missing_exts) + ')')

        # finally add it
        self._parsers_list.append(parser)

    class ActiveParsingPlan(BaseParser.ParsingPlan[T]):
        """
        A wrapper for the currently active parsing plan, to provide a different string representation.
        """

        def __init__(self, pp, cascadeparser):
            # explicitly dont use base constructor
            # super(CascadingParser.ActiveParsingPlan, self).__init__()
            self.pp = pp
            self.cascadeparser = cascadeparser

        def __str__(self):
            return str(self.pp) + ' (currently active parsing plan in ' + str(self.cascadeparser) + ')'

        def _execute(self, logger: Logger, *args, **kwargs) -> T:
            return self.pp._execute(logger, *args, **kwargs)

        def _get_children_parsing_plan(self) -> Dict[str, _ParsingPlanElement]:
            return self.pp._get_children_parsing_plan()

        def __getattr__(self, item):
            # Redirect anything that is not implemented here to the base parsing plan.
            # this is called only if the attribute was not found the usual way

            # easy version of the dynamic proxy just to save time :)
            # see http://code.activestate.com/recipes/496741-object-proxying/ for "the answer"
            pp = object.__getattribute__(self, 'pp')
            if hasattr(pp, item):
                return getattr(pp, item)
            else:
                raise AttributeError('\'' + self.__class__.__name__ + '\' object has no attribute \'' + item + '\'')

    class CascadingParsingPlan(_ParsingPlanElement[T]):
        """
        Represents a parsing plan built by multiple parsers. It is at any time a proxy of the most appropriate parsing
        plan
        """

        def _execute(self, logger: Logger, *args, **kwargs) -> T:
            raise NotImplementedError('This method is not implemented directly but though inner parsing plans. '
                                      'This should not be called normally')

        def __init__(self, desired_type: Type[T], obj_on_filesystem: PersistedObject, parser: AnyParser[T],
                     parser_list: List[BaseParser], logger: Logger):

            super(CascadingParser.CascadingParsingPlan, self).__init__(desired_type, obj_on_filesystem, parser)

            # --parser list
            check_var(parser_list, var_types=list, var_name='parser_list', min_len=1)
            self.parser_list = parser_list

            # -- the variables that will contain the active parser and its parsing plan
            self.active_parser_idx = -1
            self.active_parsing_plan = None
            self.parsing_plan_creation_errors = dict()

            # -- activate the next one
            self.activate_next_working_parser(logger=logger)

        def activate_next_working_parser(self, already_caught_execution_errors: Dict[AnyParser, Exception] = None,
                                         logger: Logger = None):
            """
            Utility method to activate the next working parser. It iteratively asks each parser of the list to create
            a parsing plan, and stops at the first one that answers

            :param already_caught_execution_errors:
            :param logger:
            :return:
            """

            if (self.active_parser_idx+1) < len(self.parser_list):
                # ask each parser to create a parsing plan right here. Stop at the first working one
                for i in range(self.active_parser_idx+1, len(self.parser_list)):
                    p = self.parser_list[i]
                    if i > 0:
                        #print('----- Rebuilding local parsing plan with next candidate parser:')
                        if logger is not None:
                            logger.info('----- Rebuilding local parsing plan with next candidate parser:')
                    try:
                        self.active_parsing_plan = CascadingParser.ActiveParsingPlan(p.create_parsing_plan(
                            self.obj_type, self.obj_on_fs_to_parse, self.logger, in_rootcall=False), self.parser)
                        self.active_parser_idx = i
                        return
                    except Exception as e:
                        msg = StringIO()
                        print_error_to_io_stream(e, msg, print_big_traceback=False)
                        # we dont use warning because it does not show up in the correct order in the console
                        #print('----- WARNING: Caught error while creating parsing plan with parser ' + str(p) + '.')
                        logger.warning('----- WARNING: Caught error while creating parsing plan with parser ' + str(p))
                        #print(msg.getvalue())
                        logger.warning(msg.getvalue())
                        self.parsing_plan_creation_errors[p] = e
            if already_caught_execution_errors is None:
                raise CascadeError.create_for_parsing_plan_creation(self.parser, self, self.parsing_plan_creation_errors)
            else:
                caught = self.parsing_plan_creation_errors
                caught.update(already_caught_execution_errors)
                raise CascadeError.create_for_execution(self.parser, self, caught)

        def execute(self, logger: Logger, *args, **kwargs):
            """
            Delegate execution to currently active parser. In case of an exception, recompute the parsing plan and
            do it again on the next one.

            :param logger:
            :param args:
            :param kwargs:
            :return:
            """
            if self.active_parsing_plan is not None:
                execution_errors = dict()
                while self.active_parsing_plan is not None:
                    try:
                        # try to execute current plan
                        return self.active_parsing_plan.execute(logger, *args, **kwargs)
                    except Exception as e:
                        # if error, print it, save it and activate the next parser
                        msg = StringIO()
                        print_error_to_io_stream(e, msg, print_big_traceback=False)
                        # we dont use warning because it does not show up in the correct order in the console
                        #print('----- WARNING: Caught error during execution : ')
                        logger.warning('!!!! Caught error during execution : ')
                        #print(msg.getvalue())
                        logger.warning(msg.getvalue())
                        #print('----- Rebuilding local parsing plan...')
                        execution_errors[self.active_parsing_plan.parser] = e
                        self.activate_next_working_parser(execution_errors, logger)

                caught = self.parsing_plan_creation_errors
                caught.update(execution_errors)
                raise CascadeError.create_for_execution(self.parser, self, caught)
            else:
                raise Exception('Cannot execute this parsing plan : empty parser list !')

    def _create_parsing_plan(self, desired_type: Type[T], filesystem_object: PersistedObject, logger: Logger) \
            -> _ParsingPlanElement[T]:
        """
        Creates a parsing plan to parse the given filesystem object into the given desired_type.
        This overrides the method in AnyParser, in order to provide a 'cascading' parsing plan

        :param desired_type:
        :param filesystem_object:
        :param logger:
        :return:
        """
        # build the parsing plan
        logger.info(get_parsing_plan_log_str(filesystem_object, desired_type, self))
        return CascadingParser.CascadingParsingPlan(desired_type, filesystem_object, self, self._parsers_list,
                                                    logger=logger)


class ParsingChain(AnyParser[T]):
    """
    Represents a parsing chain made of a base parser and a list of converters.
    """

    def __init__(self, base_parser: AnyParser[S], converter: Converter[S, T], strict: bool,
                 base_parser_chosen_dest_type: Type[S] = None):
        """
        Constructor from a base parser and a conversion chain.
        Even if the base parser is able to parse several types or even any type, at the moment converters only support
        *one* source type that cannot be 'any'. for this reason in this constructor the caller is expected to restrict
        the parser to a unique destination type explicitly

        :param base_parser:
        """
        check_var(base_parser, var_types=AnyParser, var_name='base_parser')
        if Any in base_parser.supported_types:
            raise ValueError('Creating a parsing chain from a base parser able to parse any type is just pointless.')
        self._base_parser = base_parser

        # did the user explicitly restrict the destination type of the base parser ?
        if base_parser_chosen_dest_type is None:
            if len(base_parser.supported_types) != 1:
                raise ValueError('Cannot create a parsing chain from a parser that is able to parse several types '
                                 'without restricting it explicitly. Please set a value for '
                                 '\'base_parser_chosen_dest_type\'')
            else:
                # supported types = the parser's ones (that is, only 1)
                parser_out_type = next(iter(base_parser.supported_types))
        else:
            check_var(base_parser_chosen_dest_type, var_types=type, var_name='base_parser_chosen_dest_type')
            parser_out_type = base_parser_chosen_dest_type

        # set the converter
        check_var(converter, var_types=Converter, var_name='converter')
        if not converter.is_able_to_convert(strict=strict, from_type=parser_out_type, to_type=None):
            raise ValueError('Cannot chain this parser and this converter : types are not consistent')

        self._converter = converter
        super(ParsingChain, self).__init__(supported_types={converter.to_type},
                                           supported_exts=base_parser.supported_exts)

        check_var(strict, var_types=bool, var_name='strict')
        self.strict = strict

    def size(self):
        return self._base_parser.size() + self._converter.size()

    def __getattr__(self, item):
        # Redirect anything that is not implemented here to the base parser.
        # this is called only if the attribute was not found the usual way

        # easy version of the dynamic proxy just to save time :)
        # see http://code.activestate.com/recipes/496741-object-proxying/ for "the answer"
        bp = object.__getattribute__(self, '_base_parser')
        if hasattr(bp, item):
            return getattr(bp, item)
        else:
            raise AttributeError('\'' + self.__class__.__name__ + '\' object has no attribute \'' + item + '\'')

    def __str__(self):
        # return 'ParsingChain<' + str(self._base_parser) + (' ' if len(self._converters_list) > 0 else '') + \
        #            ' '.join(['-> ' + str(converter) for converter in self._converters_list]) + '>'
        conv_str = str(self._converter)[1:-1] if isinstance(self._converter, ConversionChain) else str(self._converter)
        return '$' + str(self._base_parser) + ' => ' + conv_str + '$'

    def __repr__(self):
        # __repr__ is supposed to offer an unambiguous representation,
        # but pprint uses __repr__ so we'd like users to see the small and readable version
        return self.__str__()

    def _parse_singlefile(self, desired_type: Type[T], file_path: str, encoding: str, logger: Logger,
                          *args, **kwargs) -> T:
        """
        Implementation of AnyParser API
        """
        # first use the base parser to parse something compliant with the conversion chain
        first = self._base_parser._parse_singlefile(self._converter.from_type, file_path, encoding,
                                                    logger, *args, **kwargs)

        # then apply the conversion chain
        return self._converter.convert(desired_type, first, logger, *args, **kwargs)

    def _get_parsing_plan_for_multifile_children(self, obj_on_fs: PersistedObject, desired_type: Type[Any],
                                                 logger: Logger) -> Dict[str, Any]:
        """
        Implementation of AnyParser API
        """
        return self._base_parser._get_parsing_plan_for_multifile_children(obj_on_fs, desired_type, logger)

    def _parse_multifile(self, desired_type: Type[T], obj: PersistedObject,
                         parsing_plan_for_children: Dict[str, BaseParser.ParsingPlan],
                         logger: Logger, *args, **kwargs) -> T:
        """
        Implementation of AnyParser API
        """
        # first use the base parser
        first = self._base_parser._parse_multifile(desired_type, obj, parsing_plan_for_children, logger, *args, **kwargs)

        # then apply the conversion chain
        return self._converter.convert(desired_type, first, logger, *args, **kwargs)