from __future__ import unicode_literals

import datetime
import decimal
import math
import six
from six.moves import xrange

from uxdbcffi._impl.libpq import libpq, ffi, PG_VERSION
from uxdbcffi._impl.exceptions import ProgrammingError
from uxdbcffi.tz import LOCAL as TZ_LOCAL


adapters = {}

# Adapters assept python objects and always return bytes, as described in
# http://initd.org/psycopg/articles/2011/01/24/psycopg2-porting-python-3-report/


class _BaseAdapter(object):
    def __init__(self, wrapped_object):
        self._wrapped = wrapped_object
        self._conn = None

    if six.PY3:

        def __bytes__(self):
            return self.getquoted()

        def __str__(self):  # huh?
            return bytes_to_ascii(self.getquoted())

    else:

        def __str__(self):
            return self.getquoted()

    @property
    def adapted(self):
        return self._wrapped

    def getquoted(self):
        raise NotImplementedError


class ISQLQuote(_BaseAdapter):
    def getquoted(self):
        pass


class AsIs(_BaseAdapter):
    def getquoted(self):
        s = self._wrapped
        if not isinstance(s, (six.binary_type, six.text_type)):
            s = six.text_type(s)
        return ascii_to_bytes(s)


_bytearray_types = (bytearray,)
try:
    _bytearray_types += (memoryview,)
except NameError:
    pass  # python 2.6


class Binary(_BaseAdapter):
    def prepare(self, connection):
        self._conn = connection

    def __conform__(self, proto):
        return self

    def getquoted(self):
        if self._wrapped is None:
            return b"NULL"

        to_length = ffi.new("size_t *")
        _wrapped = self._wrapped
        if isinstance(_wrapped, six.text_type):
            _wrapped = ascii_to_bytes(_wrapped)
        elif isinstance(_wrapped, _bytearray_types):
            _wrapped = six.binary_type(_wrapped)
        elif not six.PY3 and isinstance(_wrapped, buffer):
            _wrapped = bytes(_wrapped)
        _wrapped = ffi.new("unsigned char[]", _wrapped)

        if self._conn:
            data_pointer = libpq.PQescapeByteaConn(
                self._conn._pgconn, _wrapped, len(self._wrapped), to_length
            )
        else:
            data_pointer = libpq.PQescapeBytea(_wrapped, len(self._wrapped), to_length)

        data = ffi.string(data_pointer)[: to_length[0] - 1]
        libpq.PQfreemem(data_pointer)

        if self._conn and self._conn._equote:
            return b"".join([b"E'", data, b"'::bytea"])

        return b"".join([b"'", data, b"'::bytea"])


class Boolean(_BaseAdapter):
    def getquoted(self):
        return b"true" if self._wrapped else b"false"


class DateTime(_BaseAdapter):
    def getquoted(self):
        obj = self._wrapped
        if isinstance(obj, datetime.timedelta):
            us = ascii_to_bytes(str(obj.microseconds))
            us = b"0" * (6 - len(us)) + us
            return b"".join(
                [
                    b"'",
                    ascii_to_bytes(str(int(obj.days))),
                    b" days ",
                    ascii_to_bytes(str(int(obj.seconds))),
                    b".",
                    ascii_to_bytes(str(int(us))),
                    b" seconds'::interval",
                ]
            )
        else:
            iso = obj.isoformat()
            if isinstance(obj, datetime.datetime):
                _format = b"timestamp"
                if getattr(obj, "tzinfo", None):
                    _format = b"timestamptz"
            elif isinstance(obj, datetime.time):
                _format = b"time"
            else:
                _format = b"date"
            return b"".join([b"'", ascii_to_bytes(iso), b"'::", _format])


def Date(year, month, day):
    date = datetime.date(year, month, day)
    return DateTime(date)


def DateFromTicks(ticks):
    date = datetime.datetime.fromtimestamp(ticks).date()
    return DateTime(date)


class Decimal(_BaseAdapter):
    def getquoted(self):
        if self._wrapped.is_finite():
            value = str(self._wrapped)

            # Prepend a space in front of negative numbers
            if value.startswith("-"):
                value = " " + value
            return ascii_to_bytes(value)
        return b"'NaN'::numeric"


class Float(ISQLQuote):
    def getquoted(self):
        n = float(self._wrapped)
        if math.isnan(n):
            return b"'NaN'::float"
        elif math.isinf(n):
            if n > 0:
                return b"'Infinity'::float"
            else:
                return b"'-Infinity'::float"
        else:
            value = repr(self._wrapped)

            # Prepend a space in front of negative numbers
            if value.startswith("-"):
                value = " " + value
            return ascii_to_bytes(value)


class Int(_BaseAdapter):
    def getquoted(self):
        value = str(self._wrapped)

        # Prepend a space in front of negative numbers
        if value.startswith("-"):
            value = " " + value
        return ascii_to_bytes(value)


class List(_BaseAdapter):
    def prepare(self, connection):
        self._conn = connection

    def getquoted(self):
        length = len(self._wrapped)
        if length == 0:
            return b"'{}'"

        quoted = [None] * length
        for i in xrange(length):
            obj = self._wrapped[i]
            quoted[i] = _getquoted(obj, self._conn)
        return b"".join([b"ARRAY[", b", ".join(quoted), b"]"])


class Long(_BaseAdapter):
    def getquoted(self):
        value = str(self._wrapped)

        # Prepend a space in front of negative numbers
        if value.startswith("-"):
            value = " " + value
        return ascii_to_bytes(value)


def Time(hour, minutes, seconds, tzinfo=None):
    time = datetime.time(hour, minutes, seconds, tzinfo=tzinfo)
    return DateTime(time)


def TimeFromTicks(ticks):
    time = datetime.datetime.fromtimestamp(ticks).time()
    return DateTime(time)


def Timestamp(year, month, day, hour, minutes, seconds, tzinfo=None):
    dt = datetime.datetime(year, month, day, hour, minutes, seconds, tzinfo=tzinfo)
    return DateTime(dt)


def TimestampFromTicks(ticks):
    dt = datetime.datetime.fromtimestamp(ticks, TZ_LOCAL)
    return DateTime(dt)


class QuotedString(_BaseAdapter):
    def __init__(self, obj):
        super(QuotedString, self).__init__(obj)
        self._default_encoding = "latin1"

    def prepare(self, conn):
        self._conn = conn

    @property
    def encoding(self):
        if self._conn:
            return self._conn._py_enc
        else:
            return self._default_encoding

    def getquoted(self):
        obj = self._wrapped
        if isinstance(obj, six.text_type):
            obj = obj.encode(self.encoding)
        else:
            assert isinstance(obj, six.binary_type)
        string = obj
        length = len(string)

        to_length = (length * 2) + 1
        to = ffi.new("char []", to_length)

        if not self._conn:
            libpq.PQescapeString(to, string, length)
            return b"".join([b"'", ffi.string(to), b"'"])

        if PG_VERSION < 0x090000:
            err = ffi.new("int *")
            libpq.PQescapeStringConn(self._conn._pgconn, to, string, length, err)
            if self._conn and self._conn._equote:
                return b"".join([b"E'", ffi.string(to), b"'"])
            return b"".join([b"'", ffi.string(to), b"'"])

        data_pointer = libpq.PQescapeLiteral(self._conn._pgconn, string, length)
        data = ffi.string(data_pointer)
        libpq.PQfreemem(data_pointer)
        return data


def adapt(value, proto=ISQLQuote, alt=None):
    """Return the adapter for the given value"""
    obj_type = type(value)
    try:
        return adapters[(obj_type, proto)](value)
    except KeyError:
        for subtype in obj_type.mro()[1:]:
            try:
                return adapters[(subtype, proto)](value)
            except KeyError:
                pass

    conform = getattr(value, "__conform__", None)
    if conform is not None:
        return conform(proto)
    raise ProgrammingError("can't adapt type '%s'" % obj_type.__name__)


def _getquoted(param, conn):
    """Helper method"""
    if param is None:
        return b"NULL"
    if isinstance(param, _BaseAdapter):
        adapter = param
    else:
        adapter = adapt(param)
    try:
        adapter.prepare(conn)
    except AttributeError:
        pass
    return adapter.getquoted()


def ascii_to_bytes(s):
    """Convert ascii string to bytes"""
    if isinstance(s, six.text_type):
        return s.encode("ascii")
    else:
        assert isinstance(s, six.binary_type)
        return s


def bytes_to_ascii(b):
    """Convert ascii bytestring to string"""
    assert isinstance(b, six.binary_type)
    return b.decode("ascii")


built_in_adapters = {
    bool: Boolean,
    str: QuotedString,
    list: List,
    bytearray: Binary,
    int: Int,
    float: Float,
    datetime.date: DateTime,  # DateFromPY
    datetime.datetime: DateTime,  # TimestampFromPy
    datetime.time: DateTime,  # TimeFromPy
    datetime.timedelta: DateTime,  # IntervalFromPy
    decimal.Decimal: Decimal,
}

try:
    built_in_adapters[memoryview] = Binary
except NameError:
    pass  # Python 2.6

try:
    built_in_adapters[buffer] = Binary
except NameError:
    pass  # Python 3

try:
    built_in_adapters[unicode] = QuotedString
except NameError:
    pass  # Python 3

try:
    built_in_adapters[long] = Long
except NameError:
    pass  # Python 3 - Int handles all numbers fine

if six.PY3:
    built_in_adapters[bytes] = Binary


for k, v in built_in_adapters.items():
    adapters[(k, ISQLQuote)] = v
