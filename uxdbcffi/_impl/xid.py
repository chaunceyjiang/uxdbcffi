from __future__ import unicode_literals

import re
import six
import base64

from uxdbcffi._impl import consts
from uxdbcffi._impl.cursor import Cursor


class Xid(object):
    def __init__(self, format_id, gtrid, bqual):
        if not 0 <= format_id <= 0x7FFFFFFF:
            raise ValueError("format_id must be a non-negative 32-bit integer")

        if len(gtrid) > 64:
            raise ValueError("gtrid must be a string no longer than 64 characters")

        for char in gtrid:
            if not 0x20 <= ord(char) <= 0x7F:
                raise ValueError("gtrid must contain only printable characters")

        if len(bqual) > 64:
            raise ValueError("bqual must be a string no longer than 64 characters")

        for char in bqual:
            if not 0x20 <= ord(char) <= 0x7F:
                raise ValueError("bqual must contain only printable characters")

        self.format_id = format_id
        self.gtrid = gtrid
        self.bqual = bqual

        self.prepared = None
        self.owner = None
        self.database = None

    def as_tid(self):
        if self.format_id is not None:
            gtrid = base64.b64encode(six.b(self.gtrid))
            bqual = base64.b64encode(six.b(self.bqual))
            return "%d_%s_%s" % (int(self.format_id), gtrid.decode(), bqual.decode())
        else:
            return self.gtrid

    def __str__(self):
        return self.as_tid()

    @classmethod
    def from_string(self, s, _re=re.compile("^(\\d+)_([^_]*)_([^_]*)$")):
        m = _re.match(s)
        if m is not None:
            try:
                format_id = int(m.group(1))
                gtrid = base64.b64decode(six.b(m.group(2)))
                bqual = base64.b64decode(six.b(m.group(3)))
                return Xid(format_id, gtrid.decode(), bqual.decode())
            except Exception:
                pass

        # parsing failed: unparsed xid
        xid = Xid(0, "", "")
        xid.gtrid = s
        xid.format_id = None
        xid.bqual = None

        return xid

    def __getitem__(self, idx):
        if idx < 0:
            idx += 3

        if idx == 0:
            return self.format_id
        elif idx == 1:
            return self.gtrid
        elif idx == 2:
            return self.bqual
        raise IndexError("index out of range")

    @classmethod
    def tpc_recover(self, conn):
        # should we rollback?
        rb = conn.status == consts.STATUS_READY and not conn.autocommit

        cur = conn.cursor(cursor_factory=Cursor)
        try:
            cur.execute(
                "SELECT gid, prepared, owner, database " "FROM ux_prepared_xacts"
            )

            rv = []
            for gid, prepared, owner, database in cur:
                xid = Xid.from_string(gid)
                xid.prepared = prepared
                xid.owner = owner
                xid.database = database
                rv.append(xid)

            return rv

        finally:
            if rb:
                conn.rollback()
