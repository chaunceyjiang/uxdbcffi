try:
    from uxdbcffi._impl._libpq import ffi, lib as libpq
except ImportError:
    from uxdbcffi._impl._build_libpq import ffi, C_SOURCE, C_SOURCE_KWARGS

    libpq = ffi.verify(C_SOURCE, **C_SOURCE_KWARGS)

PG_VERSION = libpq._PG_VERSION
