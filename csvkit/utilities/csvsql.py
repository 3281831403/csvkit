#!/usr/bin/env python
import os.path
import sys

import agate
import agatesql  # noqa: F401
from sqlalchemy import MetaData, create_engine, dialects, inspect
from sqlalchemy import Table as SATable

from csvkit.cli import CSVKitUtility, isatty, parse_list
from csvkit.exceptions import DuplicateColumnError, SchemaMismatchError

try:
    import importlib_metadata
except ImportError:
    import importlib.metadata as importlib_metadata

DIALECTS = dialects.__all__ + tuple(e.name for e in importlib_metadata.entry_points(group='sqlalchemy.dialects'))


class CSVSQL(CSVKitUtility):
    description = 'Generate SQL statements for one or more CSV files, or execute those statements directly on a ' \
                  'database, and execute one or more SQL queries.'
    # Override 'f' because the utility accepts multiple files.
    override_flags = ['f']

    def add_arguments(self):
        self.argparser.add_argument(
            metavar='FILE', nargs='*', dest='input_paths', default=['-'],
            help='The CSV file(s) to operate on. If omitted, will accept input as piped data via STDIN.')
        self.argparser.add_argument(
            '-i', '--dialect', dest='dialect', choices=DIALECTS,
            help='Dialect of SQL to generate. Cannot be used with --db.')
        self.argparser.add_argument(
            '--db', dest='connection_string',
            help='If present, a SQLAlchemy connection string to use to directly execute generated SQL on a database.')
        self.argparser.add_argument(
            '--engine-option', dest='engine_option', nargs=2, action='append', default=[],
            help="A keyword argument to SQLAlchemy's create_engine(), as a space-separated pair. "
                 "This option can be specified multiple times. For example: thick_mode True")
        self.argparser.add_argument(
            '--query', dest='queries', action='append',
            help='Execute one or more SQL queries delimited by --sql-delimiter, and output the result of the last '
                 'query as CSV. QUERY may be a filename. --query may be specified multiple times.')
        self.argparser.add_argument(
            '--insert', dest='insert', action='store_true',
            help='Insert the data into the table. Requires --db.')
        self.argparser.add_argument(
            '--prefix', action='append', default=[],
            help='Add an expression following the INSERT keyword, like OR IGNORE or OR REPLACE.')
        self.argparser.add_argument(
            '--before-insert', dest='before_insert',
            help='Before the INSERT command, execute one or more SQL queries delimited by --sql-delimiter. '
                 'Requires --insert.')
        self.argparser.add_argument(
            '--after-insert', dest='after_insert',
            help='After the INSERT command, execute one or more SQL queries delimited by --sql-delimiter. '
                 'Requires --insert.')
        self.argparser.add_argument(
            '--sql-delimiter', dest='sql_delimiter', default=';',
            help='Delimiter separating SQL queries in --query, --before-insert, and --after-insert.')
        self.argparser.add_argument(
            '--tables', dest='table_names',
            help='A comma-separated list of names of tables to be created. By default, the tables will be named after '
                 'the filenames without extensions or "stdin". If a single name is given, all input files are loaded '
                 'into that one table. Otherwise, one name per input file is required.')
        self.argparser.add_argument(
            '--no-constraints', dest='no_constraints', action='store_true',
            help='Generate a schema without length limits or null checks. Useful when sampling big tables.')
        self.argparser.add_argument(
            '--unique-constraint', dest='unique_constraint',
            help='A column-separated list of names of columns to include in a UNIQUE constraint.')
        self.argparser.add_argument(
            '--no-create', dest='no_create', action='store_true',
            help='Skip creating the table. Requires --insert.')
        self.argparser.add_argument(
            '--create-if-not-exists', dest='create_if_not_exists', action='store_true',
            help='Create the table if it does not exist, otherwise keep going. Requires --insert.')
        self.argparser.add_argument(
            '--overwrite', dest='overwrite', action='store_true',
            help='Drop the table if it already exists. Requires --insert. Cannot be used with --no-create.')
        self.argparser.add_argument(
            '--db-schema', dest='db_schema',
            help='Optional name of database schema to create table(s) in.')
        self.argparser.add_argument(
            '-y', '--snifflimit', dest='sniff_limit', type=int, default=1024,
            help='Limit CSV dialect sniffing to the specified number of bytes. '
                 'Specify "0" to disable sniffing entirely, or "-1" to sniff the entire file.')
        self.argparser.add_argument(
            '-I', '--no-inference', dest='no_inference', action='store_true',
            help='Disable type inference (and --locale, --date-format, --datetime-format, --no-leading-zeroes) '
                 'when parsing the input.')
        self.argparser.add_argument(
            '--chunk-size', dest='chunk_size', type=int,
            help='Chunk size for batch insert into the table. Requires --insert.')
        self.argparser.add_argument(
            '--min-col-len', dest='min_col_len', type=int, default=1,
            help='The minimum length of text columns.')
        self.argparser.add_argument(
            '--col-len-multiplier', dest='col_len_multiplier', type=int, default=1,
            help='Multiply the maximum column length by this multiplier to accomodate larger values in later runs.')

    def main(self):
        if isatty(sys.stdin) and self.args.input_paths == ['-']:
            self.argparser.error('You must provide an input file or piped data.')

        self.unique_constraint = []

        if self.args.unique_constraint:
            self.unique_constraint = self.args.unique_constraint.split(',')

        # Create a SQLite database in memory if no connection string is specified
        if self.args.queries and not self.args.connection_string:
            self.args.connection_string = "sqlite:///:memory:"
            self.args.insert = True

        if self.args.dialect and self.args.connection_string:
            self.argparser.error('The --dialect option is only valid when neither --db nor --query are specified.')
        if self.args.insert and not self.args.connection_string:
            self.argparser.error('The --insert option is only valid when either --db or --query is specified.')

        if self.args.no_create and not self.args.insert:
            self.argparser.error('The --no-create option is only valid if --insert is also specified.')
        if self.args.create_if_not_exists and not self.args.insert:
            self.argparser.error('The --create-if-not-exists option is only valid if --insert is also specified.')
        if self.args.overwrite and not self.args.insert:
            self.argparser.error('The --overwrite option is only valid if --insert is also specified.')
        if self.args.overwrite and self.args.no_create:
            self.argparser.error('The --overwrite option is only valid if --no-create is not specified.')
        if self.args.before_insert and not self.args.insert:
            self.argparser.error('The --before-insert option is only valid if --insert is also specified.')
        if self.args.after_insert and not self.args.insert:
            self.argparser.error('The --after-insert option is only valid if --insert is also specified.')
        if self.args.chunk_size and not self.args.insert:
            self.argparser.error('The --chunk-size option is only valid if --insert is also specified.')

        if self.args.no_create and self.args.create_if_not_exists:
            self.argparser.error('The --no-create and --create-if-not-exists options are mutually exclusive.')

        # Resolve the target table name for every input file before opening anything.
        table_names = self._resolve_table_names()

        # Lazy open files
        input_files = [self._open_input_file(path) for path in self.args.input_paths]

        engine = None
        connection = None
        try:
            # Establish database validity before reading CSV files
            if self.args.connection_string:
                try:
                    engine = create_engine(
                        self.args.connection_string, **parse_list(self.args.engine_option))
                except ImportError as e:
                    raise ImportError(
                        "You don't appear to have the necessary database backend installed for connection string "
                        "you're trying to use. Available backends include:\n\nPostgreSQL:\tpip install psycopg2\n"
                        "MySQL:\t\tpip install mysql-connector-python OR pip install mysqlclient\n\nFor details on "
                        "connection strings and other backends, please see the SQLAlchemy documentation on dialects "
                        "at:\n\nhttps://www.sqlalchemy.org/docs/dialects/"
                    ) from e

                connection = engine.connect()

            entries = self._read_and_validate(input_files, table_names)

            if connection:
                self._load_into_database(connection, engine, entries)
            else:
                self._write_create_statements(entries)
        finally:
            for f in input_files:
                f.close()

            if connection:
                connection.close()
            if engine:
                engine.dispose()

    def _resolve_table_names(self):
        """
        Return one target table name per input file.

        A single name passed to ``--tables`` is reused for every input file so
        that a batch of shards lands in one table. When several names are given,
        their count must match the number of input files.
        """
        explicit = self.args.table_names.split(',') if self.args.table_names else []

        if not explicit:
            names = []
            stdin_index = 0
            for path in self.args.input_paths:
                if path == '-':
                    # Keep the historical single-stdin name, but disambiguate several stdin inputs.
                    name = 'stdin' if stdin_index == 0 else f'stdin_{stdin_index}'
                    stdin_index += 1
                else:
                    name = os.path.splitext(os.path.basename(path))[0]
                names.append(name)
            return names

        if len(explicit) == 1:
            return explicit * len(self.args.input_paths)

        if len(explicit) != len(self.args.input_paths):
            self.argparser.error(
                f'--tables received {len(explicit)} table name(s) for {len(self.args.input_paths)} input file(s). '
                'Pass a single name to load all files into one table, or one name per input file.')

        return explicit

    def _read_and_validate(self, input_files, table_names):
        """
        Read every input file into an agate table and validate the whole batch
        before any database write can happen.

        Empty inputs are represented by ``None`` and skipped during validation
        and loading, preserving the historical behavior for empty files.
        """
        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        entries = []

        for f, table_name in zip(input_files, table_names):
            try:
                table = agate.Table.from_csv(
                    f,
                    skip_lines=self.args.skip_lines,
                    sniff_limit=sniff_limit,
                    column_types=self.get_column_types(),
                    **self.reader_kwargs,
                )
            except StopIteration:
                # Catch cases where no table data was provided and fall through
                # to query logic
                table = None

            # A table with no columns (empty input) is skipped entirely, matching
            # the historical behavior of falling through to the query logic.
            if table is not None and len(table.columns) > 0:
                self._validate_columns(f, table)
                entries.append((f, table_name, table))

        self._validate_shared_schemas(entries)

        return entries

    @staticmethod
    def _file_label(f):
        return 'stdin' if f == sys.stdin else f.name

    def _validate_columns(self, f, table):
        """
        Reject column names that are not distinct in a case-insensitive
        comparison. Databases such as SQLite fold unquoted identifiers to a
        common case, so "amount" and "Amount" collide there. Failing fast with
        the file and column names gives the same deterministic result for every
        dialect instead of a dialect-specific crash or silent data loss.
        """
        seen = {}
        for name in table.column_names:
            folded = name.casefold()
            if folded in seen:
                raise DuplicateColumnError(
                    f'{self._file_label(f)}: column names {seen[folded]!r} and {name!r} are not distinct when '
                    f'compared case-insensitively. Rename one of the columns so the file has unique column names.')
            seen[folded] = name

    def _validate_shared_schemas(self, entries):
        """
        Ensure that all files loaded into the same table share the same column
        names in the same order. A different layout would silently place rows in
        the wrong columns, so it is rejected before any database write with the
        offending file and columns named.

        Inferred value types are deliberately not compared: shards legitimately
        differ (e.g. a sparse or text-formatted value in an otherwise numeric
        column) and the database still stores them. A genuinely incompatible
        value fails the insert inside the all-or-nothing transaction instead.
        """
        reference = {}

        for f, table_name, table in entries:
            names = tuple(table.column_names)

            if table_name not in reference:
                reference[table_name] = (f, names)
                continue

            ref_file, ref_names = reference[table_name]
            if names != ref_names:
                raise SchemaMismatchError(
                    f'{self._file_label(f)}: cannot load into table {table_name!r}: its columns {list(names)} do not '
                    f'match the columns {list(ref_names)} of {self._file_label(ref_file)}. All files loaded into the '
                    'same table must have the same column names in the same order.')

    def _load_into_database(self, connection, engine, entries):
        """
        Load the whole batch inside a single transaction. Any failure rolls the
        transaction back and removes tables this run created or replaced (some
        backends, including SQLite, auto-commit DDL, so a rollback alone can leave
        an empty table behind), making a failed run fully rerunnable.
        """
        # Tables this run is responsible for and must drop on failure: freshly
        # created tables, plus pre-existing tables that --overwrite replaced.
        managed_tables = []
        # The snapshot of already-existing tables is taken lazily, inside the
        # transaction and only after --before-insert has run: a before-insert
        # statement may attach the named schema (SQLite), which the inspector
        # can only see on a connection where the attach happened.
        preexisting_tables = None

        try:
            with connection.begin():
                # A table is created only for the first file targeting it; later
                # files sharing the name insert into the already-created table.
                seen_tables = set()
                for f, table_name, table in entries:
                    if self.args.before_insert:
                        for query in self.args.before_insert.split(self.args.sql_delimiter):
                            connection.exec_driver_sql(query)

                    if preexisting_tables is None:
                        preexisting_tables = set(
                            inspect(connection).get_table_names(schema=self.args.db_schema))

                    first_for_table = table_name not in seen_tables
                    create = not self.args.no_create and first_for_table

                    # Register ownership BEFORE to_sql: the table is created on
                    # entry to to_sql, but its insert can then fail, so tracking
                    # it afterwards would skip cleanup and leak an empty table.
                    # --overwrite replaces even a pre-existing table; otherwise a
                    # pre-existing table that is not created is left untouched.
                    if create and table_name not in managed_tables and (
                        self.args.overwrite or table_name not in preexisting_tables
                    ):
                        managed_tables.append(table_name)

                    table.to_sql(
                        connection,
                        table_name,
                        overwrite=self.args.overwrite,
                        create=create,
                        create_if_not_exists=self.args.create_if_not_exists,
                        insert=self.args.insert and len(table.rows) > 0,
                        prefixes=self.args.prefix,
                        db_schema=self.args.db_schema,
                        constraints=not self.args.no_constraints,
                        unique_constraint=self.unique_constraint,
                        chunk_size=self.args.chunk_size,
                        min_col_len=self.args.min_col_len,
                        col_len_multiplier=self.args.col_len_multiplier,
                    )

                    seen_tables.add(table_name)

                    if self.args.after_insert:
                        for query in self.args.after_insert.split(self.args.sql_delimiter):
                            connection.exec_driver_sql(query)

                if self.args.queries:
                    self._run_queries(connection)
        except BaseException:
            # Never let a cleanup problem mask the original failure.
            try:
                self._cleanup_failed_load(connection, engine, managed_tables)
            except Exception as cleanup_error:
                self.error_file.write(
                    f'Warning: could not clean up table(s) after the failed run: {cleanup_error}\n')
            raise

    def _cleanup_failed_load(self, connection, engine, managed_tables):
        """
        Drop tables that the failed run created or replaced, so that it leaves
        neither rows nor an empty table behind. Tables the run did not touch are
        never dropped.

        The load connection is reused on purpose: a named schema may have been
        attached by a --before-insert statement, and that attach is per-connection,
        so a fresh connection would not see the schema to clean up. The failed
        transaction has already been rolled back, leaving the connection usable.
        """
        if not managed_tables:
            return

        # The failed transaction has been rolled back, but inspecting starts a
        # new (read-only) transaction; commit it first so the cleanup transaction
        # below can begin. The load connection is reused on purpose for the
        # per-connection schema attach described above.
        surviving = set(inspect(connection).get_table_names(schema=self.args.db_schema))
        connection.commit()
        metadata = MetaData(schema=self.args.db_schema)
        with connection.begin():
            for table_name in managed_tables:
                if table_name in surviving:
                    SATable(table_name, metadata, schema=self.args.db_schema).drop(
                        bind=connection, checkfirst=True)

    def _run_queries(self, connection):
        queries = []
        for query in self.args.queries:
            if os.path.exists(query):
                with open(query) as f:
                    query = f.read()
            queries += query.split(self.args.sql_delimiter)

        # Execute the specified SQL queries.
        rows = None

        for query in queries:
            if query.strip():
                rows = connection.exec_driver_sql(query)

        # Output the result of the last query as CSV
        if rows.returns_rows:
            output = agate.csv.writer(self.output_file, **self.writer_kwargs)
            output.writerow(rows._metadata.keys)
            for row in rows:
                output.writerow(row)

    def _write_create_statements(self, entries):
        """
        Emit one CREATE TABLE statement per distinct target table. All files
        sharing a table name have already been validated to share its schema.
        """
        emitted = set()

        for f, table_name, table in entries:
            if table_name in emitted:
                continue
            emitted.add(table_name)

            statement = table.to_sql_create_statement(
                table_name,
                dialect=self.args.dialect,
                db_schema=self.args.db_schema,
                constraints=not self.args.no_constraints,
                unique_constraint=self.unique_constraint,
            )

            self.output_file.write(f'{statement}\n')


def launch_new_instance():
    utility = CSVSQL()
    utility.run()


if __name__ == '__main__':
    launch_new_instance()
