import io
import os
import sqlite3
import sys
import unittest
from contextlib import redirect_stderr
from textwrap import dedent
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError, OperationalError

from csvkit.exceptions import DuplicateColumnError, SchemaMismatchError
from csvkit.utilities.csvsql import CSVSQL, launch_new_instance
from csvkit.utilities.sql2csv import SQL2CSV
from tests.utils import CSVKitTestCase, EmptyFileTests, stdin_as_string


class TestCSVSQL(CSVKitTestCase, EmptyFileTests):
    Utility = CSVSQL

    def test_launch_new_instance(self):
        with patch.object(sys, 'argv', [self.Utility.__name__.lower(), 'examples/dummy.csv']):
            launch_new_instance()

    def test_options(self):
        for args, message in (
            (
                ['--db', 'sqlite:///:memory:', '--dialect', 'sqlite'],
                'The --dialect option is only valid when neither --db nor --query are specified.',
            ),
            (
                ['--insert'],
                'The --insert option is only valid when either --db or --query is specified.',
            ),
            (
                ['--db', 'sqlite:///:memory:', '--insert', '--no-create', '--overwrite'],
                'The --overwrite option is only valid if --no-create is not specified.',
            ),
            (
                ['--db', 'sqlite:///:memory:', '--insert', '--no-create', '--create-if-not-exists'],
                'The --no-create and --create-if-not-exists options are mutually exclusive.',
            ),
        ):
            with self.subTest(args=args):
                self.assertError(launch_new_instance, args, message)

    def test_insert_options(self):
        for args in (
            ['--no-create'],
            ['--create-if-not-exists'],
            ['--overwrite'],
            ['--before-insert'],
            ['--after-insert'],
            ['--chunk-size', '1'],
        ):
            with self.subTest(args=args):
                self.assertError(
                    launch_new_instance,
                    args,
                    f'The {args[0]} option is only valid if --insert is also specified.'
                )

    def setUp(self):
        self.db_file = 'foo.db'

    def tearDown(self):
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

    @unittest.skipIf(os.name != 'nt', 'Windows only')
    def test_glob(self):
        sql = self.get_output(['examples/dummy?.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE dummy2 (
              a BOOLEAN NOT NULL, 
              b DECIMAL NOT NULL, 
              c DECIMAL NOT NULL
            );
            CREATE TABLE dummy3 (
              a BOOLEAN NOT NULL, 
              b DECIMAL NOT NULL, 
              c DECIMAL NOT NULL
            );
        '''))  # noqa: W291

    def test_create_table(self):
        sql = self.get_output(['--tables', 'foo', 'examples/testfixed_converted.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              text VARCHAR NOT NULL, 
              date DATE, 
              integer DECIMAL, 
              boolean BOOLEAN, 
              float DECIMAL, 
              time DATETIME, 
              datetime TIMESTAMP, 
              empty_column BOOLEAN
            );
        '''))  # noqa: W291

    def test_no_blanks(self):
        sql = self.get_output(['--tables', 'foo', 'examples/blanks.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              a BOOLEAN, 
              b BOOLEAN, 
              c BOOLEAN, 
              d BOOLEAN, 
              e BOOLEAN, 
              f BOOLEAN
            );
        '''))  # noqa: W291

    def test_blanks(self):
        sql = self.get_output(['--tables', 'foo', '--blanks', 'examples/blanks.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              a VARCHAR NOT NULL, 
              b VARCHAR NOT NULL, 
              c VARCHAR NOT NULL, 
              d VARCHAR NOT NULL, 
              e VARCHAR NOT NULL, 
              f VARCHAR NOT NULL
            );
        '''))  # noqa: W291

    def test_no_inference(self):
        sql = self.get_output(['--tables', 'foo', '--no-inference', 'examples/testfixed_converted.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              text VARCHAR NOT NULL, 
              date VARCHAR, 
              integer VARCHAR, 
              boolean VARCHAR, 
              float VARCHAR, 
              time VARCHAR, 
              datetime VARCHAR, 
              empty_column VARCHAR
            );
        '''))  # noqa: W291

    def test_no_header_row(self):
        sql = self.get_output(['--tables', 'foo', '--no-header-row', 'examples/no_header_row.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              a BOOLEAN NOT NULL, 
              b DECIMAL NOT NULL, 
              c DECIMAL NOT NULL
            );
        '''))  # noqa: W291

    def test_linenumbers(self):
        sql = self.get_output(['--tables', 'foo', '--linenumbers', 'examples/dummy.csv'])

        self.assertEqual(sql.replace('\t', '  '), dedent('''\
            CREATE TABLE foo (
              a BOOLEAN NOT NULL, 
              b DECIMAL NOT NULL, 
              c DECIMAL NOT NULL
            );
        '''))  # noqa: W291

    def test_stdin(self):
        input_file = io.BytesIO(b'a,b,c\n4,2,3\n')

        with stdin_as_string(input_file):
            sql = self.get_output(['--tables', 'foo'])

            self.assertEqual(sql.replace('\t', '  '), dedent('''\
                CREATE TABLE foo (
                  a DECIMAL NOT NULL, 
                  b DECIMAL NOT NULL, 
                  c DECIMAL NOT NULL
                );
            '''))  # noqa: W291

        input_file.close()

    def test_stdin_and_filename(self):
        input_file = io.BytesIO(b'a,b,c\n1,2,3\n')

        with stdin_as_string(input_file):
            sql = self.get_output(['-', 'examples/dummy.csv'])

            self.assertTrue('CREATE TABLE stdin' in sql)
            self.assertTrue('CREATE TABLE dummy' in sql)

        input_file.close()

    def test_query(self):
        input_file = io.BytesIO(b'a,b,c\n1,2,3\n')

        with stdin_as_string(input_file):
            sql = self.get_output(['--query', 'SELECT m.usda_id, avg(i.sepal_length) AS mean_sepal_length FROM iris '
                                   'AS i JOIN irismeta AS m ON (i.species = m.species) GROUP BY m.species',
                                   'examples/iris.csv', 'examples/irismeta.csv'])

            self.assertTrue('usda_id,mean_sepal_length' in sql)
            self.assertTrue('IRSE,5.00' in sql)
            self.assertTrue('IRVE2,5.936' in sql)
            self.assertTrue('IRVI,6.58' in sql)

        input_file.close()

    def test_query_empty(self):
        input_file = io.BytesIO()

        with stdin_as_string(input_file):
            output = self.get_output(['--query', 'SELECT 1'])
            self.assertEqual(output, '1\n1\n')

        input_file.close()

    def test_query_text(self):
        sql = self.get_output(['--query', 'SELECT text FROM testfixed_converted WHERE text LIKE "Chicago%"',
                               'examples/testfixed_converted.csv'])

        self.assertEqual(sql,
                         "text\n"
                         "Chicago Reader\n"
                         "Chicago Sun-Times\n"
                         "Chicago Tribune\n")

    def test_query_file(self):
        sql = self.get_output(['--query', 'examples/test_query.sql', 'examples/testfixed_converted.csv'])

        self.assertEqual(sql,
                         "question,text\n"
                         "36,©\n")

    def test_query_update(self):
        sql = self.get_output(['--query', 'UPDATE dummy SET a=10 WHERE a=1', '--no-inference', 'examples/dummy.csv'])

        self.assertEqual(sql, '')

    def test_before_after_insert(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', 'examples/dummy.csv', '--before-insert',
                         'SELECT 1; CREATE TABLE foobar (date DATE)', '--after-insert',
                         'INSERT INTO dummy VALUES (0, 5, 6)'])

        output_file = io.StringIO()
        utility = SQL2CSV(['--db', 'sqlite:///' + self.db_file, '--query', 'SELECT * FROM foobar'], output_file)
        utility.run()
        output = output_file.getvalue()
        output_file.close()
        self.assertEqual(output, 'date\n')

        output_file = io.StringIO()
        utility = SQL2CSV(['--db', 'sqlite:///' + self.db_file, '--query', 'SELECT * FROM dummy'], output_file)
        utility.run()
        output = output_file.getvalue()
        output_file.close()
        self.assertEqual(output, 'a,b,c\n1,2.0,3.0\n0,5.0,6.0\n')

    def test_no_prefix_unique_constraint(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert',
                        'examples/dummy.csv', '--unique-constraint', 'a'])
        with self.assertRaises(IntegrityError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', 'examples/dummy.csv', '--no-create'])

    def test_prefix_unique_constraint(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert',
                        'examples/dummy.csv', '--unique-constraint', 'a'])
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert',
                        'examples/dummy.csv', '--no-create', '--prefix', 'OR IGNORE'])

    def test_no_create_if_not_exists(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'foo', 'examples/foo1.csv'])
        with self.assertRaises(OperationalError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'foo', 'examples/foo2.csv'])

    def test_create_if_not_exists(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'foo', 'examples/foo1.csv'])
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables',
                        'foo', 'examples/foo2.csv', '--create-if-not-exists'])

    def _table_names(self):
        connection = sqlite3.connect(self.db_file)
        try:
            return [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        finally:
            connection.close()

    def _table_rows(self, table_name):
        connection = sqlite3.connect(self.db_file)
        try:
            return list(connection.execute(f'SELECT * FROM {table_name}'))
        finally:
            connection.close()

    def _table_columns(self, table_name):
        connection = sqlite3.connect(self.db_file)
        try:
            return [row[1] for row in connection.execute(f'PRAGMA table_info({table_name})')]
        finally:
            connection.close()

    def test_single_table_name_loads_all_shards_into_one_table(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                         'examples/batch_shard_a.csv', 'examples/batch_shard_b.csv'])

        self.assertEqual(self._table_names(), ['batched'])
        self.assertEqual(self._table_columns('batched'), ['id', 'amount'])
        self.assertEqual(self._table_rows('batched'),
                         [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0), (4.0, 40.0)])

    def test_single_table_name_ddl_emits_one_create_statement(self):
        sql = self.get_output(['--tables', 'batched',
                               'examples/batch_shard_a.csv', 'examples/batch_shard_b.csv'])

        self.assertEqual(sql.count('CREATE TABLE batched'), 1)

    def test_table_name_count_mismatch_is_an_error(self):
        output = io.StringIO()
        error = io.StringIO()
        utility = CSVSQL(['--tables', 'a,b', 'examples/batch_shard_a.csv'], output_file=output, error_file=error)
        with redirect_stderr(error), self.assertRaises(SystemExit) as e:
            utility.run()
        self.assertEqual(e.exception.code, 2)
        self.assertIn('one name per input file', error.getvalue())
        output.close()

    def test_case_only_duplicate_column_fails_before_writing(self):
        with self.assertRaises(DuplicateColumnError) as context:
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                             'examples/batch_case_dup.csv'])

        message = str(context.exception)
        self.assertIn('examples/batch_case_dup.csv', message)
        self.assertIn("'amount'", message)
        self.assertIn("'Amount'", message)
        # Nothing was created, so the failed run is directly rerunnable.
        self.assertEqual(self._table_names(), [])

    def test_case_only_duplicate_column_is_dialect_independent(self):
        for dialect in ('sqlite', 'postgresql', 'mysql'):
            with self.subTest(dialect=dialect):
                with self.assertRaises(DuplicateColumnError) as context:
                    self.get_output(['--dialect', dialect, '--tables', 'batched',
                                     'examples/batch_case_dup.csv'])
                self.assertIn('examples/batch_case_dup.csv', str(context.exception))

    def test_case_only_duplicate_column_in_batch_is_all_or_nothing(self):
        with self.assertRaises(DuplicateColumnError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                             'examples/batch_shard_a.csv', 'examples/batch_case_dup.csv'])

        # The whole batch is rolled back: no table and no rows remain.
        self.assertEqual(self._table_names(), [])

        # The same command shape succeeds once the offending shard is removed.
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                         'examples/batch_shard_a.csv', 'examples/batch_shard_b.csv'])
        self.assertEqual(len(self._table_rows('batched')), 4)

    def test_schema_drift_between_shards_fails_cleanly_and_reruns(self):
        with self.assertRaises(SchemaMismatchError) as context:
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                             'examples/batch_shard_a.csv', 'examples/batch_schema_drift.csv'])

        message = str(context.exception)
        self.assertIn('examples/batch_schema_drift.csv', message)
        self.assertIn("'extra'", message)
        self.assertEqual(self._table_names(), [])

        # A conforming rerun against the same database file works without "table already exists".
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                         'examples/batch_shard_a.csv', 'examples/batch_shard_b.csv'])
        self.assertEqual(len(self._table_rows('batched')), 4)

    def test_failed_batch_preserves_preexisting_table(self):
        connection = sqlite3.connect(self.db_file)
        connection.execute('CREATE TABLE keepme (x INTEGER)')
        connection.execute('INSERT INTO keepme VALUES (99)')
        connection.commit()
        connection.close()

        with self.assertRaises(IntegrityError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                             '--unique-constraint', 'id',
                             'examples/batch_shard_a.csv', 'examples/batch_shard_unique.csv'])

        self.assertEqual(self._table_names(), ['keepme'])
        self.assertEqual(self._table_rows('keepme'), [(99,)])

    def test_multiple_table_names_still_create_separate_tables(self):
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'one,two',
                         'examples/batch_shard_a.csv', 'examples/batch_shard_b.csv'])

        self.assertEqual(self._table_names(), ['one', 'two'])
        self.assertEqual(len(self._table_rows('one')), 2)
        self.assertEqual(len(self._table_rows('two')), 2)

    def test_heterogeneous_inferred_types_are_allowed(self):
        # The "id" column is numeric in one shard and text in another. Only the
        # column layout is validated; the database stores the values as-is.
        self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                         'examples/batch_shard_a.csv', 'examples/batch_shard_text_id.csv'])

        self.assertEqual(self._table_rows('batched'),
                         [(1.0, 10.0), (2.0, 20.0), ('abc', 20.0)])

    def test_overwrite_failure_drops_the_replaced_table(self):
        connection = sqlite3.connect(self.db_file)
        connection.execute('CREATE TABLE batched (id INTEGER, amount REAL)')
        connection.execute('INSERT INTO batched VALUES (77, 7.7)')
        connection.commit()
        connection.close()

        with self.assertRaises(IntegrityError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--tables', 'batched',
                             '--overwrite', '--unique-constraint', 'id',
                             'examples/batch_shard_a.csv', 'examples/batch_shard_unique.csv'])

        # The replaced table is removed on failure, leaving no empty table behind.
        self.assertEqual(self._table_names(), [])

    def test_failed_batch_in_named_schema_is_cleaned_up(self):
        connection = sqlite3.connect(self.db_file)
        auxiliary = self.db_file + '.aux'
        connection.execute(f"ATTACH DATABASE '{auxiliary}' AS mys")
        connection.commit()
        connection.close()

        with self.assertRaises(IntegrityError):
            self.get_output(['--db', 'sqlite:///' + self.db_file, '--insert', '--db-schema', 'mys',
                             '--tables', 'batched',
                             '--before-insert', f"ATTACH DATABASE '{auxiliary}' AS mys",
                             '--unique-constraint', 'id', 'examples/batch_shard_unique.csv'])

        connection = sqlite3.connect(self.db_file)
        connection.execute(f"ATTACH DATABASE '{auxiliary}' AS mys")
        names = [row[0] for row in connection.execute(
            "SELECT name FROM mys.sqlite_master WHERE type='table'")]
        connection.close()
        self.addCleanup(lambda: os.path.exists(auxiliary) and os.remove(auxiliary))
        self.assertEqual(names, [])

