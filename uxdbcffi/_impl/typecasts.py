from __future__ import unicode_literals

import re
import decimal
import datetime
from time import localtime
import six

from uxdbcffi._impl.libpq import libpq, ffi
from uxdbcffi._impl.adapters import bytes_to_ascii, ascii_to_bytes
from uxdbcffi._impl.exceptions import DataError

# Typecasters accept bytes and return python objects.
# This only applies to our internal typecasers - user-defined ones
# accept unicode, to mimic psycopg2 behaviour

string_types = {}

binary_types = {}


class Type(object):
    def __init__(self, name, values, caster=None, py_caster=None, accept_unicode=True):
        self.name = name
        self.values = values
        self.caster = caster
        self.py_caster = py_caster
        self.accept_unicode = accept_unicode

    def __eq__(self, other):
        return other in self.values

    def cast(self, value, cursor=None, length=None):
        if self.py_caster is not None:
            # py_caster-s are part of external api and so accept unicode
            if isinstance(value, six.binary_type) and self.accept_unicode:
                value = value.decode(cursor._conn._py_enc)
            return self.py_caster(value, cursor)
        return self.caster(value, length, cursor)

    __call__ = cast


def register_type(type_obj, scope=None):
    typecasts = string_types
    if scope:
        from uxdbcffi._impl.connection import Connection
        from uxdbcffi._impl.cursor import Cursor

        if isinstance(scope, Connection):
            typecasts = scope._typecasts
        elif isinstance(scope, Cursor):
            typecasts = scope._typecasts
        else:
            typecasts = None

    for value in type_obj.values:
        typecasts[value] = type_obj


def new_type(values, name, castobj, accept_unicode=True):
    return Type(name, values, py_caster=castobj, accept_unicode=accept_unicode)


def new_array_type(values, name, baseobj):
    caster = parse_array(baseobj)
    return Type(name, values, caster=caster)


def typecast(caster, value, length, cursor):
    return caster.cast(value, cursor, length)


def parse_unknown(value, length, cursor):
    if value is None:
        return None
    if value != b"{}":
        # FIXME hmm not sure
        if six.PY3 and isinstance(value, six.binary_type):
            return parse_unicode(value, length, cursor)
        return value
    else:
        return []


if six.PY3:

    def parse_string(value, length, cursor):
        return value.decode(cursor.connection._py_enc) if value is not None else None


else:

    def parse_string(value, length, cursor):
        return value


if six.PY3:

    def parse_longinteger(value, length, cursor):
        return int(value) if value is not None else None


else:

    def parse_longinteger(value, length, cursor):
        return long(value) if value is not None else None


def parse_integer(value, length, cursor):
    return int(value) if value is not None else None


def parse_float(value, length, cursor):
    return float(value) if value is not None else None


def parse_decimal(value, length, cursor):
    if value is None:
        return None
    if isinstance(value, six.binary_type):
        value = bytes_to_ascii(value)
    return decimal.Decimal(value)


def parse_binary(value, length, cursor):
    if value is None:
        return None

    to_length = ffi.new("size_t *")
    s = libpq.PQunescapeBytea(ffi.new("unsigned char[]", value), to_length)
    try:
        res = ffi.buffer(s, to_length[0])[:]
    finally:
        libpq.PQfreemem(s)
    return memoryview(res) if six.PY3 else buffer(res)


def parse_boolean(value, length, cursor):
    """Typecast the postgres boolean to a python boolean.

    Postgres returns the boolean as a string with 'true' or 'false'

    """
    return value[:1] == b"t" if value is not None else None


class parse_array(object):
    """Parse an array of a items using an configurable caster for the items

    The array syntax is defined as::

        '{ val1 delim val2 delim ... }'

    A two-dimensional array with string items is defined as::

        '{{"meeting", "lunch"}, {"training", "presentation"}}'

    """

    def __init__(self, caster):
        self._caster = caster

    def cast(self, value, length, cursor):
        if value is None:
            return None

        s = value
        if not (len(s) >= 2 and s[:1] == b"{" and s[-1:] == b"}"):
            raise DataError("malformed array")

        i = 1
        array = []
        stack = [array]
        value_length = len(s) - 1
        while i < value_length:
            si = s[i : i + 1]
            if si == b"{":
                sub_array = []
                array.append(sub_array)
                stack.append(sub_array)
                if len(stack) > 16:
                    raise DataError("excessive array dimensions")

                array = sub_array
                i += 1
            elif si == b"}":
                stack.pop()
                if not stack:
                    raise DataError("unbalanced braces in array")
                array = stack[-1]
                i += 1
            elif si in b", ":
                i += 1
            else:
                # Number of quotes, this will always be 0 or 2 (int vs str)
                quotes = 0

                # Whether or not the next char should be escaped
                escape_char = False

                buf = []
                while i < value_length:
                    si = s[i : i + 1]
                    if not escape_char:
                        if si == b'"':
                            quotes += 1
                        elif si == b"\\":
                            escape_char = True
                        elif quotes % 2 == 0 and (si == b"}" or si == b","):
                            break
                        else:
                            buf.append(si)
                    else:
                        escape_char = False
                        buf.append(si)

                    i += 1

                str_buf = b"".join(buf)
                if len(str_buf) == 4 and str_buf.lower() == b"null":
                    val = typecast(self._caster, None, 0, cursor)
                else:
                    val = typecast(self._caster, str_buf, len(str_buf), cursor)
                array.append(val)
        return stack[-1]

    __call__ = cast


def parse_unicode(value, length, cursor):
    """Decode the given value with the connection encoding"""
    if value is None:
        return None
    elif isinstance(value, six.text_type):
        # This can occur when we use our internal typecaster
        # in register_type, so it accepts unicode, not bytes.
        return value
    else:
        return value.decode(cursor._conn._py_enc)


def _parse_time_to_args(value, cursor):
    """Return arguemnts for datetime.time constructor

    The given value is in the format of `16:28:09.506488+01`

    """
    hour, minute, second = value.split(b":", 2)

    sign = 0
    tzinfo = None
    timezone = None
    if b"-" in second:
        sign = -1
        second, timezone = second.split(b"-")
    elif b"+" in second:
        sign = 1
        second, timezone = second.split(b"+")

    if not cursor.tzinfo_factory is None and sign:
        parts = timezone.split(b":")
        tz_min = 60 * int(parts[0])
        if len(parts) > 1:
            tz_min += int(parts[1])
        if len(parts) > 2 and int(parts[2]) >= 30:
            tz_min += 1
        tzinfo = cursor.tzinfo_factory(sign * tz_min)

    if b"." in second:
        second, frac = second.split(b".")
        micros = int((frac + (b"0" * (6 - len(frac))))[:6])
    else:
        micros = 0

    return int(hour), int(minute), int(second), micros, tzinfo


def parse_datetime(value, length, cursor):
    if value is None:
        return None
    if isinstance(value, six.text_type):
        value = ascii_to_bytes(value)
    if value == b"infinity":
        return datetime.datetime.max
    elif value == b"-infinity":
        return datetime.datetime.min

    try:
        date, time = value.split(b" ")
        date_args = date.split(b"-")
        return datetime.datetime(
            int(date_args[0]),
            int(date_args[1]),
            int(date_args[2]),
            *_parse_time_to_args(time, cursor)
        )
    except (TypeError, ValueError):
        if value.endswith(b"BC"):
            raise ValueError("BC dates not supported")
        raise DataError("bad datetime: '%s'" % bytes_to_ascii(value))


def parse_date(value, length, cursor):
    if value is None:
        return None
    if isinstance(value, six.text_type):
        value = ascii_to_bytes(value)
    if value == b"infinity":
        return datetime.date.max
    elif value == b"-infinity":
        return datetime.date.min

    try:
        return datetime.date(*[int(x) for x in value.split(b"-")])
    except (TypeError, ValueError):
        if value.endswith(b"BC"):
            raise ValueError("BC dates not supported")
        raise DataError("bad datetime: '%s'" % bytes_to_ascii(value))


def parse_time(value, length, cursor):
    if value is None:
        return None
    if isinstance(value, six.text_type):
        value = ascii_to_bytes(value)
    try:
        return datetime.time(*_parse_time_to_args(value, cursor))
    except (TypeError, ValueError):
        raise DataError("bad datetime: '%s'" % value)


_re_interval = re.compile(
    br"""
    (?:(-?\+?\d+)\sy\w+\s?)?    # year
    (?:(-?\+?\d+)\sm\w+\s?)?    # month
    (?:(-?\+?\d+)\sd\w+\s?)?    # day
    (?:(-?\+?)(\d+):(\d+):(\d+) # +/- hours:mins:secs
        (?:\.(\d+))?)?          # second fraction
    """,
    re.VERBOSE,
)


def parse_interval(value, length, cursor):
    """Typecast an interval to a datetime.timedelta instance.

    For example, the value '2 years 1 mon 3 days 10:01:39.100' is converted
    to `datetime.timedelta(763, 36099, 100)`.

    """
    if value is None:
        return None
    if isinstance(value, six.text_type):
        value = ascii_to_bytes(value)

    m = _re_interval.match(value)
    if not m:
        raise ValueError("failed to parse interval: '%s'" % value)

    years, months, days, sign, hours, mins, secs, frac = m.groups()

    days = int(days) if days is not None else 0
    if months is not None:
        days += int(months) * 30
    if years is not None:
        days += int(years) * 365

    if hours is not None:
        secs = int(hours) * 3600 + int(mins) * 60 + int(secs)
        if frac is not None:
            micros = int((frac + (b"0" * (6 - len(frac))))[:6])
        else:
            micros = 0

        if sign == b"-":
            secs = -secs
            micros = -micros
    else:
        secs = micros = 0

    return datetime.timedelta(days, secs, micros)


def Date(year, month, day):
    from uxdbcffi.extensions.adapters import DateTime

    date = datetime.date(year, month, day)
    return DateTime(date)


def DateFromTicks(ticks):
    tm = localtime()
    return Date(tm.tm_year, tm.tm_mon, tm.tm_mday)


def Binary(obj):
    from uxdbcffi.extensions.adapters import Binary

    return Binary(obj)


def _default_type(name, oids, caster):
    """Shortcut to register internal types"""
    type_obj = Type(name, oids, caster)
    register_type(type_obj)
    return type_obj


# DB API 2.0 types
BINARY = _default_type("BINARY", [17], parse_binary)
DATETIME = _default_type("DATETIME", [1114, 1184, 704, 1186], parse_datetime)
NUMBER = _default_type("NUMBER", [20, 33, 21, 701, 700, 1700], parse_float)
ROWID = _default_type("ROWID", [26], parse_integer)
STRING = _default_type("STRING", [19, 18, 25, 1042, 1043], parse_string)

# Register the basic typecasters
BOOLEAN = _default_type("BOOLEAN", [16], parse_boolean)
DATE = _default_type("DATE", [1082], parse_date)
DECIMAL = _default_type("DECIMAL", [1700], parse_decimal)
FLOAT = _default_type("FLOAT", [701, 700], parse_float)
INTEGER = _default_type("INTEGER", [23, 21], parse_integer)
INTERVAL = _default_type("INTERVAL", [704, 1186], parse_interval)
LONGINTEGER = _default_type("LONGINTEGER", [20], parse_longinteger)
TIME = _default_type("TIME", [1083, 1266], parse_time)
UNKNOWN = _default_type("UNKNOWN", [705], parse_unknown)

# Array types
BINARYARRAY = _default_type("BINARYARRAY", [1001], parse_array(BINARY))
BOOLEANARRAY = _default_type("BOOLEANARRAY", [1000], parse_array(BOOLEAN))
DATEARRAY = _default_type("DATEARRAY", [1182], parse_array(DATE))
DATETIMEARRAY = _default_type("DATETIMEARRAY", [1115, 1185], parse_array(DATETIME))
DECIMALARRAY = _default_type("DECIMALARRAY", [1231], parse_array(DECIMAL))
FLOATARRAY = _default_type("FLOATARRAY", [1017, 1021, 1022], parse_array(FLOAT))
INTEGERARRAY = _default_type("INTEGERARRAY", [1005, 1006, 1007], parse_array(INTEGER))
INTERVALARRAY = _default_type("INTERVALARRAY", [1187], parse_array(INTERVAL))
LONGINTEGERARRAY = _default_type("LONGINTEGERARRAY", [1016], parse_array(LONGINTEGER))
ROWIDARRAY = _default_type("ROWIDARRAY", [1013, 1028], parse_array(ROWID))
STRINGARRAY = _default_type(
    "STRINGARRAY", [1002, 1003, 1009, 1014, 1015], parse_array(STRING)
)
TIMEARRAY = _default_type("TIMEARRAY", [1183, 1270], parse_array(TIME))


UNICODE = Type("UNICODE", [19, 18, 25, 1042, 1043], parse_unicode)
UNICODEARRAY = Type(
    "UNICODEARRAY", [1002, 1003, 1009, 1014, 1015], parse_array(UNICODE)
)
