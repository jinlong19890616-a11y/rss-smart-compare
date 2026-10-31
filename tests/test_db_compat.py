import unittest
from unittest.mock import Mock
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'rsssubscribe_smart'))

class DbCompatTests(unittest.TestCase):
    def test_sqlite_does_not_execute_postgres_transaction_statement(self):
        db=Mock(); db.bind.dialect.name='sqlite'
        if db.bind.dialect.name == 'postgresql':
            db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
        db.connection().exec_driver_sql.assert_not_called()
    def test_postgres_executes_read_only_statement(self):
        db=Mock(); db.bind.dialect.name='postgresql'
        if db.bind.dialect.name == 'postgresql':
            db.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
        db.connection().exec_driver_sql.assert_called_once_with('SET TRANSACTION READ ONLY')
