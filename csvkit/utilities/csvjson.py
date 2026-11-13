#!/usr/bin/env python

import json
import sys
from collections import OrderedDict
from decimal import Decimal

import agate

from csvkit.cli import CSVKitUtility, default_str_decimal, match_column_identifier


class CSVJSON(CSVKitUtility):
    description = 'Convert a CSV file into JSON (or GeoJSON).'

    def add_arguments(self):
        self.argparser.add_argument(
            '-i', '--indent', dest='indent', type=int,
            help='Indent the output JSON this many spaces. Disabled by default.')
        self.argparser.add_argument(
            '-k', '--key', dest='key',
            help='Output JSON as an object keyed by a given column, KEY, rather than as an array. All column values '
                 'must be unique. If --lat and --lon are specified, this column is used as the GeoJSON Feature ID.')
        self.argparser.add_argument(
            '--lat', dest='lat',
            help='A column index or name containing a latitude. Output will be GeoJSON instead of JSON. '
                 'Requires --lon. Column indices are 1-based, or 0-based with --zero.')
        self.argparser.add_argument(
            '--lon', dest='lon',
            help='A column index or name containing a longitude. Output will be GeoJSON instead of JSON. '
                 'Requires --lat. Column indices are 1-based, or 0-based with --zero.')
        self.argparser.add_argument(
            '--type', dest='type',
            help='A column index or name containing a GeoJSON type. Output will be GeoJSON instead of JSON. '
                 'Requires --lat and --lon.')
        self.argparser.add_argument(
            '--geometry', dest='geometry',
            help='A column index or name containing a GeoJSON geometry. Output will be GeoJSON instead of JSON. '
                 'Requires --lat and --lon.')
        self.argparser.add_argument(
            '--crs', dest='crs',
            help='A coordinate reference system string to be included with GeoJSON output. Requires --lat and --lon.')
        self.argparser.add_argument(
            '--no-bbox', dest='no_bbox', action='store_true',
            help='Disable the calculation of a bounding box.')
        self.argparser.add_argument(
            '--stream', dest='streamOutput', action='store_true',
            help='Output JSON as a stream of newline-separated objects, rather than an as an array.')
        self.argparser.add_argument(
            '-y', '--snifflimit', dest='sniff_limit', type=int, default=1024,
            help='Limit CSV dialect sniffing to the specified number of bytes. '
                 'Specify "0" to disable sniffing entirely, or "-1" to sniff the entire file.')
        self.argparser.add_argument(
            '-I', '--no-inference', dest='no_inference', action='store_true',
            help='Disable type inference (and --locale, --date-format, --datetime-format, --no-leading-zeroes) '
                 'when parsing the input.')

    def main(self):
        """
        Convert CSV to JSON.
        """
        if self.args.lat and not self.args.lon:
            self.argparser.error('--lon is required whenever --lat is specified.')
        if self.args.lon and not self.args.lat:
            self.argparser.error('--lat is required whenever --lon is specified.')

        if self.args.crs and not self.args.lat:
            self.argparser.error('--crs is only allowed when --lat and --lon are also specified.')
        if self.args.type and not self.args.lat:
            self.argparser.error('--type is only allowed when --lat and --lon are also specified.')
        if self.args.geometry and not self.args.lat:
            self.argparser.error('--geometry is only allowed when --lat and --lon are also specified.')

        if self.args.key and self.args.streamOutput and not (self.args.lat and self.args.lon):
            self.argparser.error('--key is only allowed with --stream when --lat and --lon are also specified.')

        self.json_kwargs = {
            'indent': self.args.indent,
        }

        if self.can_stream():
            if self.additional_input_expected():
                sys.stderr.write('No input file or piped data provided. Waiting for standard input:\n')

            if self.is_geo():
                self.streaming_output_ndgeojson()
            else:
                self.streaming_output_ndjson()

        else:
            if self.additional_input_expected():
                self.argparser.error('You must provide an input file or piped data.')

            if self.is_geo():
                self.output_geojson()
            else:
                self.output_json()

    def dump_json(self, data, newline=False):
        json.dump(data, self.output_file, default=default_str_decimal, ensure_ascii=False, **self.json_kwargs)
        if newline:
            self.output_file.write("\n")

    def can_stream(self):
        return (
            self.args.streamOutput
            and self.args.no_inference
            and self.args.sniff_limit == 0
            and not self.args.skip_lines
        )

    def is_geo(self):
        return self.args.lat and self.args.lon

    def read_csv_to_table(self):
        sniff_limit = self.args.sniff_limit if self.args.sniff_limit != -1 else None
        return agate.Table.from_csv(
            self.input_file,
            skip_lines=self.args.skip_lines,
            sniff_limit=sniff_limit,
            column_types=self.get_column_types(),
            **self.reader_kwargs,
        )

    def output_json(self):
        self.read_csv_to_table().to_json(
            self.output_file,
            key=self.args.key,
            newline=self.args.streamOutput,
            indent=self.args.indent,
        )

    def output_geojson(self):
        table = self.read_csv_to_table()
        geojson_generator = self.GeoJsonGenerator(self.args, table.column_names, table.column_types)

        if self.args.streamOutput:
            for line_number, row in enumerate(table.rows, start=1):
                self.dump_json(geojson_generator.feature_for_row(row, line_number), newline=True)
        else:
            self.dump_json(geojson_generator.generate_feature_collection(table))

    def streaming_output_ndjson(self):
        rows = agate.csv.reader(self.input_file, **self.reader_kwargs)
        column_names = next(rows)

        for row in rows:
            data = OrderedDict()
            for i, column in enumerate(column_names):
                try:
                    data[column] = row[i]
                except IndexError:
                    data[column] = None
            self.dump_json(data, newline=True)

    def streaming_output_ndgeojson(self):
        rows = agate.csv.reader(self.input_file, **self.reader_kwargs)
        column_names = next(rows)
        geojson_generator = self.GeoJsonGenerator(self.args, column_names)

        for line_number, row in enumerate(rows, start=1):
            self.dump_json(geojson_generator.feature_for_row(row, line_number), newline=True)

    class GeoJsonGenerator:
        def __init__(self, args, column_names, column_types=None):
            self.args = args
            self.column_names = column_names
            # In streaming mode every value is a raw string, so no type-specific conversion is needed.
            self.json_funcs = [column_type.jsonify for column_type in column_types] if column_types else []

            column_offset = 1
            if getattr(args, 'zero_based', False):
                column_offset = 0

            self.lat_column = match_column_identifier(column_names, self.args.lat, column_offset)

            self.lon_column = match_column_identifier(column_names, self.args.lon, column_offset)

            if self.args.type:
                self.type_column = match_column_identifier(column_names, self.args.type, column_offset)
            else:
                self.type_column = None

            if self.args.geometry:
                self.geometry_column = match_column_identifier(column_names, self.args.geometry, column_offset)
            else:
                self.geometry_column = None

            if self.args.key:
                self.id_column = match_column_identifier(column_names, self.args.key, column_offset)
            else:
                self.id_column = None

            self.seen_ids = set()

        def generate_feature_collection(self, table):
            features = []
            bounds = self.GeoJsonBounds()

            for line_number, row in enumerate(table.rows, start=1):
                feature = self.feature_for_row(row, line_number)

                if not self.args.no_bbox:
                    bounds.add_feature(feature)

                features.append(feature)

            items = [
                ('type', 'FeatureCollection'),
                ('features', features),
            ]

            if not self.args.no_bbox and bounds.min_lon is not None:
                items.insert(1, ('bbox', bounds.bbox()))

            if self.args.crs:
                items.append(('crs', OrderedDict([
                    ('type', 'name'),
                    ('properties', {
                        'name': self.args.crs,
                    }),
                ])))

            return OrderedDict(items)

        def value_for_column(self, value, index):
            """
            Convert a row value the same way plain JSON output does, so that GeoJSON shares its
            typing rules: numbers stay numeric (including 0), dates are ISO strings, and only
            genuine nulls become ``None``.
            """
            if self.json_funcs:
                return self.json_funcs[index](value)
            return value

        def feature_id(self, value):
            """
            Match the key conversion used by agate's plain JSON ``key`` output.
            """
            if isinstance(value, Decimal):
                return str(value.normalize())
            return value

        def feature_for_row(self, row, line_number=None):
            feature = OrderedDict([
                ('type', 'Feature'),
                ('properties', OrderedDict()),
            ])

            for i, c in enumerate(row):
                # Prevent "type" or geo fields from being added to properties.
                if i in (self.type_column, self.lat_column, self.lon_column, self.geometry_column):
                    continue

                value = self.value_for_column(c, i)

                if i == self.id_column:
                    # Only genuine nulls are omitted, so an empty-string id is still set.
                    if c is not None:
                        # Use the raw cell value, so Decimal ids follow agate's key conversion
                        # (e.g. Decimal('1.0') becomes "1"), rather than jsonify's float output.
                        feature_id = self.feature_id(c)
                        self.check_unique_id(feature_id)
                        feature['id'] = feature_id
                elif c is not None:
                    # Keep 0, False and the empty string; omit only genuine nulls.
                    feature['properties'][self.column_names[i]] = value

            feature['geometry'] = self.geometry_for_row(row, line_number)

            return feature

        def check_unique_id(self, feature_id):
            # agate's plain JSON -k output rejects duplicate keys with this message.
            key = str(feature_id)
            if key in self.seen_ids:
                raise ValueError('Value %s is not unique in the key column.' % key)
            self.seen_ids.add(key)

        def geometry_for_row(self, row, line_number=None):
            lat = None
            lon = None

            if self.geometry_column is not None:
                geometry = row[self.geometry_column]
                if geometry is None or geometry == '':
                    return None
                try:
                    return json.loads(geometry)
                except json.JSONDecodeError as e:
                    sys.stderr.write(
                        'Row %i has invalid GeoJSON in column "%s": %s\n'
                        % (line_number, self.column_names[self.geometry_column], e.msg))
                    return None

            if self.lat_column is not None and self.lon_column is not None:
                try:
                    lon = float(row[self.lon_column])
                    lat = float(row[self.lat_column])
                except (TypeError, ValueError):
                    lon = None
                    lat = None

            if lon is not None and lat is not None:
                return OrderedDict([
                    ('type', 'Point'),
                    ('coordinates', [lon, lat]),
                ])

        class GeoJsonBounds:
            def __init__(self):
                self.min_lon = None
                self.min_lat = None
                self.max_lon = None
                self.max_lat = None

            def bbox(self):
                return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]

            def add_feature(self, feature):
                if feature.get('geometry') and 'coordinates' in feature['geometry']:
                    self.update_coordinates(feature['geometry']['coordinates'])

            def update_lat(self, lat):
                if self.min_lat is None or lat < self.min_lat:
                    self.min_lat = lat
                if self.max_lat is None or lat > self.max_lat:
                    self.max_lat = lat

            def update_lon(self, lon):
                if self.min_lon is None or lon < self.min_lon:
                    self.min_lon = lon
                if self.max_lon is None or lon > self.max_lon:
                    self.max_lon = lon

            def update_coordinates(self, coordinates):
                if len(coordinates) <= 3 and isinstance(coordinates[0], (float, int)):
                    self.update_lon(coordinates[0])
                    self.update_lat(coordinates[1])
                else:
                    for coordinate in coordinates:
                        self.update_coordinates(coordinate)


def launch_new_instance():
    utility = CSVJSON()
    utility.run()


if __name__ == '__main__':
    launch_new_instance()
