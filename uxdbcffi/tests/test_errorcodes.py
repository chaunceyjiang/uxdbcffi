from unittest import TestCase

from psycopg2cffi import errorcodes


class TestErrorcodes(TestCase):
    def test_lookup(self):
        self.assertEqual(errorcodes.lookup('54001'), 'STATEMENT_TOO_COMPLEX')
        self.assertRaises(KeyError, errorcodes.lookup, '41234')
