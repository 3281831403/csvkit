import io
import sys
from unittest.mock import patch

import agate

from csvkit.utilities.csvformat import CSVFormat, launch_new_instance
from tests.utils import CSVKitTestCase, EmptyFileTests, stdin_as_string


class TestCSVFormat(CSVKitTestCase, EmptyFileTests):
    Utility = CSVFormat

    def test_launch_new_instance(self):
        with patch.object(sys, 'argv', [self.Utility.__name__.lower(), 'examples/dummy.csv']):
            launch_new_instance()

    def test_skip_lines(self):
        self.assertLines(['--skip-lines', '3', '-D', '|', 'examples/test_skip_lines.csv'], [
            'a|b|c',
            '1|2|3',
        ])

    def test_skip_header(self):
        self.assertLines(['--skip-header', 'examples/dummy.csv'], [
            '1,2,3',
        ])

    def test_empty_header_options(self):
        with stdin_as_string(io.BytesIO(b'')):
            self.assertLines(['--skip-header'], [])
        with stdin_as_string(io.BytesIO(b'')):
            self.assertLines(['--no-header-row'], [])
        self.assertLines(['--no-header-row', '--skip-lines', '2', 'examples/dummy.csv'], [])

    def test_skip_header_no_header_row(self):
        self.assertLines(['--no-header-row', '--skip-header', 'examples/no_header_row.csv'], [
            '1,2,3',
        ])

    def test_no_header_row(self):
        self.assertLines(['--no-header-row', 'examples/no_header_row.csv'], [
            'a,b,c',
            '1,2,3',
        ])

    def test_linenumbers(self):
        self.assertLines(['--linenumbers', 'examples/dummy.csv'], [
            'line_number,a,b,c',
            '1,1,2,3',
        ])

    def test_delimiter(self):
        self.assertLines(['-D', '|', 'examples/dummy.csv'], [
            'a|b|c',
            '1|2|3',
        ])

    def test_tabs(self):
        self.assertLines(['-T', 'examples/dummy.csv'], [
            'a\tb\tc',
            '1\t2\t3',
        ])

    def test_asv(self):
        self.assertLines(['-A', 'examples/dummy.csv'], [
            'a\x1fb\x1fc\x1e1\x1f2\x1f3\x1e',
        ], newline_at_eof=False)

    def test_quotechar(self):
        input_file = io.BytesIO(b'a,b,c\n1#2,3,4\n')

        with stdin_as_string(input_file):
            self.assertLines(['-Q', '#'], [
                'a,b,c',
                '#1##2#,3,4',
            ])

        input_file.close()

    def test_doublequote(self):
        input_file = io.BytesIO(b'a\n"a ""quoted"" string"')

        with stdin_as_string(input_file):
            self.assertLines(['-P', '#', '-B'], [
                'a',
                'a #"quoted#" string',
            ])

        input_file.close()

    def test_escapechar(self):
        input_file = io.BytesIO(b'a,b,c\n1"2,3,4\n')

        with stdin_as_string(input_file):
            self.assertLines(['-P', '#', '-U', '3'], [
                'a,b,c',
                '1#"2,3,4',
            ])

        input_file.close()

    def test_lineterminator(self):
        self.assertLines(['-M', 'XYZ', 'examples/dummy.csv'], [
            'a,b,cXYZ1,2,3XYZ',
        ], newline_at_eof=False)


class TestCSVFormatQuoteNonNumeric(CSVKitTestCase, EmptyFileTests):
    Utility = CSVFormat

    # New test compared to TestCSVFormat.
    def test_locale(self):
        self.assertLines(['-U', '2', '--locale', 'de_DE', 'examples/test_locale.csv'], [
            '"a","b","c"',
            '1.7,200000000,""',
        ])

    # New tests compared to TestCSVFormat: without an explicit --locale, -U 2 changes
    # only the quoting, never the values or the shape of the rows.
    def test_values_preserved(self):
        self.assertLines(['-U', '2', 'examples/test_quote_nonnumeric.csv'], [
            '"id","state","code","ratio"',
            '1,"none",00123,1e3',
            '2,"NULL",00456,2.5',
            '3,"n/a",".",3',
            '4,".",00789,4',
        ])

    def test_blank_line_preserved(self):
        with stdin_as_string(io.BytesIO(b'a,b,c\n1,2,3\n\n4,5,6\n')):
            self.assertLines(['-U', '2'], [
                '"a","b","c"',
                '1,2,3',
                '',
                '4,5,6',
            ])

    def test_ragged_rows_preserved(self):
        with stdin_as_string(io.BytesIO(b'a,b,c\n1,2\n4,5,6,7\n')):
            self.assertLines(['-U', '2'], [
                '"a","b","c"',
                '1,2',
                '4,5,6,7',
            ])

    def test_same_rows_as_quote_minimal(self):
        # Anything -U 0 can read, -U 2 must also read, row for row.
        for path in ('examples/test_quote_nonnumeric.csv',):
            minimal = self.get_output_as_list(['-U', '0', path])
            nonnumeric = self.get_output_as_list(['-U', '2', path])
            self.assertEqual(len(minimal), len(nonnumeric))
            for min_row, nn_row in zip(minimal, nonnumeric):
                self.assertEqual(
                    next(agate.csv.reader([min_row])),
                    next(agate.csv.reader([nn_row])),
                )

    def test_launch_new_instance(self):
        with patch.object(sys, 'argv', [self.Utility.__name__.lower(), 'examples/dummy.csv']):
            launch_new_instance()

    def test_skip_lines(self):
        self.assertLines(['-U', '2', '--skip-lines', '3', '-D', '|', 'examples/test_skip_lines.csv'], [
            '"a"|"b"|"c"',
            '1|2|3',
        ])

    def test_skip_header(self):
        self.assertLines(['-U', '2', '--skip-header', 'examples/dummy.csv'], [
            '1,2,3',
        ])

    def test_skip_header_no_header_row(self):
        self.assertLines(['-U', '2', '--no-header-row', '--skip-header', 'examples/no_header_row.csv'], [
            '1,2,3',
        ])

    def test_no_header_row(self):
        self.assertLines(['-U', '2', '--no-header-row', 'examples/no_header_row.csv'], [
            '"a","b","c"',
            '1,2,3',
        ])

    def test_linenumbers(self):
        self.assertLines(['-U', '2', '--linenumbers', 'examples/dummy.csv'], [
            '"line_number","a","b","c"',
            '1,1,2,3',
        ])

    def test_delimiter(self):
        self.assertLines(['-U', '2', '-D', '|', 'examples/dummy.csv'], [
            '"a"|"b"|"c"',
            '1|2|3',
        ])

    def test_tabs(self):
        self.assertLines(['-U', '2', '-T', 'examples/dummy.csv'], [
            '"a"\t"b"\t"c"',
            '1\t2\t3',
        ])

    def test_asv(self):
        self.assertLines(['-U', '2', '-A', 'examples/dummy.csv'], [
            '"a"\x1f"b"\x1f"c"\x1e1\x1f2\x1f3\x1e',
        ], newline_at_eof=False)

    def test_quotechar(self):
        input_file = io.BytesIO(b'a,b,c\n1#2,3,4\n')

        with stdin_as_string(input_file):
            self.assertLines(['-U', '2', '-Q', '#'], [
                '#a#,#b#,#c#',
                '#1##2#,3,4',
            ])

        input_file.close()

    def test_doublequote(self):
        input_file = io.BytesIO(b'a\n"a ""quoted"" string"')

        with stdin_as_string(input_file):
            self.assertLines(['-U', '2', '-P', '#', '-B'], [
                '"a"',
                '"a #"quoted#" string"',
            ])

        input_file.close()

    def test_escapechar(self):
        input_file = io.BytesIO(b'a,b,c\n1"2,3,4\n')

        with stdin_as_string(input_file):
            self.assertLines(['-U', '2', '-P', '#', '-U', '3'], [
                'a,b,c',
                '1#"2,3,4',
            ])

        input_file.close()

    def test_lineterminator(self):
        self.assertLines(['-U', '2', '-M', 'XYZ', 'examples/dummy.csv'], [
            '"a","b","c"XYZ1,2,3XYZ',
        ], newline_at_eof=False)
