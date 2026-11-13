#!/usr/bin/env python

import datetime
import sys

import agate

from csvkit.cli import CSVKitUtility, isatty, match_column_identifier


def _normalize_join_key(value):
    """
    Normalize a join key so that values compare equal across differing inferred
    column types, e.g. the number 10 and the text "10".
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return str(value)


def _join_key_function(column_index, normalize):
    """
    Create a join key function reading the column at the given index. Keys are
    normalized only when the two join columns were inferred as different types,
    so that same-type joins keep their exact existing behavior.
    """
    if normalize:
        def join_key(row):
            return _normalize_join_key(row[column_index])
    else:
        def join_key(row):
            return row[column_index]

    return join_key


class CSVJoin(CSVKitUtility):
    description = 'Execute a SQL-like join to merge CSV files on a specified column or columns.'
    epilog = "Note that the join operation requires reading all files into memory. Don't try this on very large files."
    # Override 'f' because the utility accepts multiple files.
    override_flags = ['f']

    def add_arguments(self):
        self.argparser.add_argument(
            metavar='FILE', nargs='*', dest='input_paths', default=['-'],
            help='The CSV files to operate on. If only one is specified, it will be copied to STDOUT.')
        self.argparser.add_argument(
            '-c', '--columns', dest='columns',
            help='The column name(s) on which to join. Should be either one name (or index) or a comma-separated list '
                 'with one name (or index) per file, in the same order in which the files were specified. If not '
                 'specified, the two files will be joined sequentially without matching.')
        self.argparser.add_argument(
            '--outer', dest='outer_join', action='store_true',
            help='Perform a full outer join, rather than the default inner join.')
        self.argparser.add_argument(
            '--left', dest='left_join', action='store_true',
            help='Perform a left outer join, rather than the default inner join. If more than two files are provided '
                 'this will be executed as a sequence of left outer joins, starting at the left.')
        self.argparser.add_argument(
            '--right', dest='right_join', action='store_true',
            help='Perform a right outer join, rather than the default inner join. If more than two files are provided '
                 'this will be executed as a sequence of right outer joins, starting at the right.')
        self.argparser.add_argument(
            '-y', '--snifflimit', dest='sniff_limit', type=int, default=1024,
            help='Limit CSV dialect sniffing to the specified number of bytes. '
                 'Specify "0" to disable sniffing entirely, or "-1" to sniff the entire file.')
        self.argparser.add_argument(
            '-I', '--no-inference', dest='no_inference', action='store_true',
            help='Disable type inference (and --locale, --date-format, --datetime-format, --no-leading-zeroes) '
                 'when parsing the input.')

    def main(self):
        if isatty(sys.stdin) and self.args.input_paths == ['-']:
            self.argparser.error('You must provide an input file or piped data.')

        self.input_files = []

        for path in self.args.input_paths:
            self.input_files.append(self._open_input_file(path))

        if self.args.columns:
            join_column_names = self._parse_join_column_names(self.args.columns)

            if len(join_column_names) == 1:
                join_column_names = join_column_names * len(self.input_files)

            if len(join_column_names) != len(self.input_files):
                self.argparser.error('The number of join column names must match the number of files, or be a single '
                                     'column name that exists in all files.')

        if (self.args.left_join or self.args.right_join or self.args.outer_join) and not self.args.columns:
            self.argparser.error('You must provide join column names when performing an outer join.')

        if self.args.left_join and self.args.right_join:
            self.argparser.error('It is not valid to specify both a left and a right join.')

        tables = []
        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        column_types = self.get_column_types()

        for f in self.input_files:
            tables.append(agate.Table.from_csv(
                f,
                skip_lines=self.args.skip_lines,
                sniff_limit=sniff_limit,
                column_types=column_types,
                **self.reader_kwargs,
            ))
            f.close()

        join_column_ids = []

        if self.args.columns:
            for i, table in enumerate(tables):
                join_column_ids.append(match_column_identifier(table.column_names, join_column_names[i]))

        jointab = tables[0]

        if self.args.left_join:
            # Left outer join
            for i, table in enumerate(tables[1:]):
                jointab = self._join_tables(jointab, table, join_column_ids[0], join_column_ids[i + 1])
        elif self.args.right_join:
            # Right outer join
            jointab = tables[-1]

            remaining_tables = tables[:-1]
            remaining_tables.reverse()

            for i, table in enumerate(remaining_tables):
                jointab = self._join_tables(jointab, table, join_column_ids[-1], join_column_ids[-(i + 2)])
        elif self.args.outer_join:
            # Full outer join
            for i, table in enumerate(tables[1:]):
                jointab = self._join_tables(
                    jointab, table, join_column_ids[0], join_column_ids[i + 1], full_outer=True)
        elif self.args.columns:
            # Inner join
            for i, table in enumerate(tables[1:]):
                jointab = self._join_tables(jointab, table, join_column_ids[0], join_column_ids[i + 1], inner=True)
        else:
            # Sequential join
            for table in tables[1:]:
                jointab = agate.Table.join(jointab, table, full_outer=True)

        jointab.to_csv(self.output_file, **self.writer_kwargs)

    def _join_tables(self, left_table, right_table, left_column, right_column, inner=False, full_outer=False):
        """
        Join two tables on the columns at the given indices.

        If the two join columns were inferred as different types (e.g. one is
        numeric and the other contains non-numeric values), their keys are
        compared as strings so that equal-looking values still match. The
        columns themselves keep their inferred types in the output.
        """
        normalize = type(left_table.column_types[left_column]) is not type(right_table.column_types[right_column])
        left_key = _join_key_function(left_column, normalize)
        right_key = _join_key_function(right_column, normalize)

        if full_outer:
            # In the output of a full outer join, the right table's columns
            # follow the left table's columns in order.
            right_key_column = len(left_table.column_names) + right_column
            joined = agate.Table.join(left_table, right_table, left_key, right_key, full_outer=True)

            # agate leaves the left join column empty for rows that only exist
            # in the right table. Fill it with the right join column's value so
            # that every output row carries its join key.
            rows = []

            for row in joined.rows:
                row = list(row)

                if row[left_column] is None and row[right_key_column] is not None:
                    row[left_column] = row[right_key_column]

                rows.append(row)

            return joined._fork(rows)

        # Exclude the right join column from the output, as agate does when
        # joining on column names.
        columns = [name for i, name in enumerate(right_table.column_names) if i != right_column]

        return agate.Table.join(left_table, right_table, left_key, right_key, inner=inner, columns=columns)

    def _parse_join_column_names(self, join_string):
        """
        Parse a list of join columns.
        """
        return list(map(str.strip, join_string.split(',')))


def launch_new_instance():
    utility = CSVJoin()
    utility.run()


if __name__ == '__main__':
    launch_new_instance()
