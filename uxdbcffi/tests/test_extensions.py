from psycopg2cffi.extensions import AsIs

def test_asis_with_integer():
    # as documented here: http://initd.org/psycopg/docs/extensions.html#psycopg2.extensions.AsIs
    assert AsIs(42).getquoted() == b'42'
