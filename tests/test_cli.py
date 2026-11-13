import unittest

from csvkit.cli import ColumnIdentifierError, match_column_identifier, parse_column_identifiers


class TestCli(unittest.TestCase):

    def setUp(self):
        self.headers = ['id', 'name', 'i_work_here', '1', 'more-header-values', 'stuff', 'blueberry']

    def test_match_column_identifier_string(self):
        self.assertEqual(2, match_column_identifier(self.headers, 'i_work_here'))
        self.assertEqual(2, match_column_identifier(self.headers, 'i_work_here', column_offset=0))

    def test_match_column_identifier_numeric(self):
        self.assertEqual(2, match_column_identifier(self.headers, 3))
        self.assertEqual(3, match_column_identifier(self.headers, 3, column_offset=0))

    def test_match_column_which_could_be_integer_name_is_treated_as_positional_id(self):
        self.assertEqual(0, match_column_identifier(self.headers, '1'))
        self.assertEqual(1, match_column_identifier(self.headers, '1', column_offset=0))

    def test_match_column_numeric_name_out_of_positional_range(self):
        # A numeric identifier that isn't a valid position still matches an exact column name.
        headers = ['id', 'name', '2024']
        self.assertEqual(2, match_column_identifier(headers, '2024'))
        self.assertEqual(2, match_column_identifier(headers, '2024', column_offset=0))
        self.assertEqual(2, parse_column_identifiers('2024', headers)[0])

    def test_match_column_numeric_name_zero(self):
        # A column named "0" is out of range for 1-based indexing, so the name wins.
        headers = ['0', 'name']
        self.assertEqual(0, match_column_identifier(headers, '0'))
        # ...but with --zero, "0" is a valid position, which takes priority.
        self.assertEqual(0, match_column_identifier(headers, '0', column_offset=0))

    def test_parse_column_identifiers(self):
        self.assertEqual([2, 0, 1], parse_column_identifiers('i_work_here,1,name', self.headers))
        self.assertEqual([2, 1, 1], parse_column_identifiers('i_work_here,1,name', self.headers, column_offset=0))
        self.assertEqual(
            [1, 1],
            parse_column_identifiers(
                'i_work_here,1,name',
                self.headers,
                column_offset=0,
                excluded_columns='i_work_here,foobar',
            ),
        )

    def test_range_notation(self):
        self.assertEqual([0, 1, 2], parse_column_identifiers('1:3', self.headers))
        self.assertEqual([1, 2, 3], parse_column_identifiers('1:3', self.headers, column_offset=0))
        self.assertEqual([1, 2, 3], parse_column_identifiers('2-4', self.headers))
        self.assertEqual([2, 3, 4], parse_column_identifiers('2-4', self.headers, column_offset=0))
        self.assertEqual([0, 1, 2, 3], parse_column_identifiers('1,2:4', self.headers))
        self.assertEqual([1, 2, 3, 4], parse_column_identifiers('1,2:4', self.headers, column_offset=0))
        self.assertEqual([4, 2, 5], parse_column_identifiers('more-header-values,3,stuff', self.headers))
        self.assertEqual([4, 3, 5], parse_column_identifiers(
            'more-header-values,3,stuff', self.headers, column_offset=0))

    def test_ignore_unknown_columns(self):
        self.assertEqual(
            [0, 2],
            parse_column_identifiers('id,nope,i_work_here', self.headers, ignore_unknown_columns=True),
        )
        self.assertEqual(
            [],
            parse_column_identifiers('nope,missing', self.headers, ignore_unknown_columns=True),
        )
        # An unknown identifier containing '-' or ':' is skipped too, not parsed as a range.
        self.assertEqual(
            [0, 2],
            parse_column_identifiers('id,no-pe,i_work_here', self.headers, ignore_unknown_columns=True),
        )
        # Without the flag, the same input still raises.
        with self.assertRaises(ColumnIdentifierError):
            parse_column_identifiers('id,no-pe,i_work_here', self.headers)

    def test_exclude_open_ended_range(self):
        # An open-ended exclusion range reaches the last column.
        self.assertEqual(
            [0, 1, 2, 3, 4],
            parse_column_identifiers(None, self.headers, excluded_columns='6-'),
        )

    def test_exclude_ignores_unknown_names_but_reports_invalid_ranges(self):
        # An unknown bare name is skipped (long-standing -C tolerance)...
        self.assertEqual(
            [0, 1, 2, 3, 4, 5, 6],
            parse_column_identifiers(None, self.headers, excluded_columns='nope'),
        )
        # ...but a malformed range is a user error, even for -C.
        with self.assertRaises(ColumnIdentifierError):
            parse_column_identifiers(None, self.headers, excluded_columns='no-pe')
        # ...as is a range that references a nonexistent column.
        with self.assertRaises(ColumnIdentifierError):
            parse_column_identifiers(None, self.headers, excluded_columns='6-99')

    def test_range_notation_open_ended(self):
        self.assertEqual([0, 1, 2], parse_column_identifiers(':3', self.headers))

        target = list(range(3, len(self.headers)))  # protect against devs adding to self.headers
        target.insert(0, 0)
        self.assertEqual(target, parse_column_identifiers('1,4:', self.headers))

        target = list(range(0, len(self.headers)))
        self.assertEqual(target, parse_column_identifiers('1:', self.headers))

    def test_range_notation_open_ended_zero(self):
        self.assertEqual([0, 1, 2, 3], parse_column_identifiers(':3', self.headers, column_offset=0))

        target = list(range(4, len(self.headers)))  # protect against devs adding to self.headers
        target.insert(0, 1)
        self.assertEqual(target, parse_column_identifiers('1,4:', self.headers, column_offset=0))

        target = list(range(0, len(self.headers)))
        self.assertEqual(target, parse_column_identifiers('0:', self.headers, column_offset=0))
