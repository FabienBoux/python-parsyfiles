from logging import Logger
from typing import Dict, List, Any, Union, Type

import pandas as pd

from parsyfiles.converting_core import Converter, ConverterFunction, T
from parsyfiles.parsing_core import SingleFileParserFunction, AnyParser


# def read_simpledf_from_xls_streaming(desired_type: Type[pd.DataFrame], file_object: TextIOBase,
#                            logger: Logger, *args, **kwargs) -> pd.DataFrame:
#     """
#     Helper method to read a dataframe from a xls file stream. By default this is well suited for a dataframe with
#     headers in the first row, for example a parameter dataframe.
#     :param file_object:
#     :return:
#     """
#     return pd.read_excel(file_object, *args, **kwargs)


def read_dataframe_from_xls(desired_type: Type[T], file_path: str, encoding: str,
                            logger: Logger, *args, **kwargs) -> pd.DataFrame:
    """
    We register this method rather than the other because pandas guesses the encoding by itself.

    Also, it is easier to put a breakpoint and debug by trying various options to find the good one (in streaming mode
    you just have one try and then the stream is consumed)

    :param desired_type:
    :param file_path:
    :param encoding:
    :param logger:
    :param args:
    :param kwargs:
    :return:
    """
    return pd.read_excel(file_path, *args, **kwargs)


def read_df_or_series_from_csv(desired_type: Type[pd.DataFrame], file_path: str, encoding: str,
                               logger: Logger, *args, **kwargs) -> pd.DataFrame:
    """
    Helper method to read a dataframe from a csv file stream. By default this is well suited for a dataframe with
    headers in the first row, for example a parameter dataframe.
    :param file_object:
    :return:
    """
    if desired_type is pd.Series:
        # as recommended in http://pandas.pydata.org/pandas-docs/stable/generated/pandas.Series.from_csv.html
        # and from http://stackoverflow.com/questions/15760856/how-to-read-a-pandas-series-from-a-csv-file

        # TODO there should be a way to decide between row-oriented (squeeze=True) and col-oriented (index_col=0)
        # note : squeeze=true only works for row-oriented, so we dont use it. We rather expect that a row-oriented
        # dataframe would be convertible to a series using the df to series converter below
        one_col_df = pd.read_csv(file_path, encoding=encoding, index_col=0, *args, **kwargs)
        if one_col_df.shape[1] == 1:
            return one_col_df[one_col_df.columns[0]]
        else:
            raise Exception('Cannot build a series from this csv: it has more than two columns (one index + one value).'
                            ' Probably the parsing chain $read_df_or_series_from_csv => single_row_or_col_df_to_series$'
                            'will work, though.')
    else:
        return pd.read_csv(file_path, encoding=encoding, *args, **kwargs)


def get_default_dataframe_parsers() -> List[AnyParser]:
    """
    Utility method to return the default parsers able to parse a dictionary from a file.
    :return:
    """
    return [SingleFileParserFunction(parser_function=read_dataframe_from_xls,
                                     streaming_mode=False,
                                     supported_exts={'.xls', '.xlsx', '.xlsm'},
                                     supported_types={pd.DataFrame}),
            SingleFileParserFunction(parser_function=read_df_or_series_from_csv,
                                     streaming_mode=False,
                                     supported_exts={'.csv', '.txt'},
                                     supported_types={pd.DataFrame, pd.Series}),
            ]


def dict_to_single_row_or_col_df(desired_type: Type[T], dict_obj: Dict, logger: Logger,
                                 orient: str = None, *args, **kwargs) -> pd.DataFrame:
    """
    Helper method to convert a dictionary into a dataframe with one row

    :param dict_obj:
    :return:
    """
    orient = orient or 'columns'
    if orient is 'columns':
        return pd.DataFrame(dict_obj, index=[0])
    else:
        res = pd.DataFrame.from_dict(dict_obj, orient='index')
        res.index.name = 'key'
        return res.rename(columns={0:'value'})


def single_row_or_col_df_to_series(desired_type: Type[T], single_rowcol_df: pd.DataFrame, logger: Logger, *args, **kwargs)\
        -> pd.Series:
    """
    Helper method to convert a dataframe with one row or one or two columns into a Series

    :param desired_type:
    :param single_col_df:
    :param logger:
    :param args:
    :param kwargs:
    :return:
    """
    if single_rowcol_df.shape[0] == 1:
        # one row
        return single_rowcol_df.transpose()[0]
    elif single_rowcol_df.shape[1] == 2 and isinstance(single_rowcol_df.index, pd.RangeIndex):
        # two columns but the index contains nothing but the row number : we can use the first column
        d = single_rowcol_df.set_index(single_rowcol_df.columns[0])
        return d[d.columns[0]]
    elif single_rowcol_df.shape[1] == 1:
        # one column and one index
        d = single_rowcol_df
        return d[d.columns[0]]
    else:
        raise ValueError('Unable to convert provided dataframe to a series : '
                         'expected exactly 1 row or 1 column, found : ' + str(single_rowcol_df.shape) + '')


def single_row_or_col_df_to_dict(desired_type: Type[T], single_rowcol_df: pd.DataFrame, logger: Logger, *args, **kwargs)\
        -> Dict[str, str]:
    """
    Helper method to convert a dataframe with one row or one or two columns into a dictionary

    :param single_rowcol_df:
    :return:
    """
    if single_rowcol_df.shape[0] == 1:
        return single_rowcol_df.transpose()[0].to_dict()
        # return {col_name: single_rowcol_df[col_name][single_rowcol_df.index.values[0]] for col_name in single_rowcol_df.columns}
    elif single_rowcol_df.shape[1] == 2 and isinstance(single_rowcol_df.index, pd.RangeIndex):
        # two columns but the index contains nothing but the row number : we can use the first column
        d = single_rowcol_df.set_index(single_rowcol_df.columns[0])
        return d[d.columns[0]].to_dict()
    elif single_rowcol_df.shape[1] == 1:
        # one column and one index
        d = single_rowcol_df
        return d[d.columns[0]].to_dict()
    else:
        raise ValueError('Unable to convert provided dataframe to a parameters dictionary : '
                         'expected exactly 1 row or 1 column, found : ' + str(single_rowcol_df.shape) + '')


def get_default_dataframe_converters() -> List[Union[Converter[Any, pd.DataFrame],
                                                     Converter[pd.DataFrame, Any]]]:
    """
    Utility method to return the default converters associated to dataframes (from dataframe to other type,
    and from other type to dataframe)
    :return:
    """
    return [ConverterFunction(pd.DataFrame, dict, single_row_or_col_df_to_dict),
            ConverterFunction(dict, pd.DataFrame, dict_to_single_row_or_col_df),
            ConverterFunction(pd.DataFrame, pd.Series, single_row_or_col_df_to_series)]
