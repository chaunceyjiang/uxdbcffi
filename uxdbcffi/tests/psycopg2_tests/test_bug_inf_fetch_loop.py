#!/usr/bin/env python
#
# bug_info_fetch_loop.py - test for bug with infinite loop, when 
# result size exceeds cursor.itersize

import psycopg2cffi as psycopg2
from psycopg2cffi.tests.psycopg2_tests.testconfig import dsn
from psycopg2cffi.tests.psycopg2_tests.testutils import unittest


class CursorTests(unittest.TestCase):

    def setUp(self):
        self.conn = psycopg2.connect(dsn)

    def tearDown(self):
        self.conn.close()

    def test(self):
        ''' Test for bug https://github.com/chtd/psycopg2cffi/issues/1
        '''
        curs = self.conn.cursor()
        curs.itersize = 10
        curs.execute('create table inf_fetch_loop (id integer)')

        for i in range(curs.itersize * 2):
            curs.execute('insert into inf_fetch_loop values (%s)', (2 * i,))

        curs.execute('select * from inf_fetch_loop')
        result = [(curs.rownumber, row) for row in curs]
        self.assertEqual(result, [(1 + i % curs.itersize, (2 * i,)) 
            for i in range(curs.itersize * 2)])


