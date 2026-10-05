"""Internal offline evidence receiver. No route, dispatch, promotion or training."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .learning_bundle import capture, pack, unpack, verify
from .sqlite_policy import configure_connection, enable_wal


class LearningReceiver:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.resolve().drive.upper() == 'F:':
            raise ValueError('receiver outputs belong on X:, not the source drive')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('CREATE TABLE IF NOT EXISTS learning_evidence ('
                                   'revision TEXT NOT NULL PRIMARY KEY, bundle BLOB NOT NULL, '
                                   'bundle_sha256 TEXT NOT NULL)')
                self._validate_schema(connection)

    def _connect(self):
        return configure_connection(sqlite3.connect(self.path, timeout=5))

    @staticmethod
    def _validate_schema(connection):
        columns = connection.execute('PRAGMA table_info(learning_evidence)').fetchall()
        expected = [(0, 'revision', 'TEXT', 1, None, 1),
                    (1, 'bundle', 'BLOB', 1, None, 0),
                    (2, 'bundle_sha256', 'TEXT', 1, None, 0)]
        indexes = connection.execute('PRAGMA index_list(learning_evidence)').fetchall()
        triggers = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' "
                                      "AND tbl_name='learning_evidence'").fetchall()
        if (columns != expected or len(indexes) != 1 or indexes[0][2:] != (1, 'pk', 0)
                or triggers):
            raise ValueError('receiver schema/uniqueness differs')

    def ingest(self, export_file, episode_file, receipt_file):
        bundle = capture(export_file, episode_file, receipt_file)
        value = verify(bundle, self.path.parent)
        raw = pack(bundle)
        digest = hashlib.sha256(raw).hexdigest()
        with closing(self._connect()) as connection:
            with connection:
                connection.execute('BEGIN IMMEDIATE')
                self._validate_schema(connection)
                row = connection.execute('SELECT bundle,bundle_sha256 FROM learning_evidence '
                                         'WHERE revision=?', (value['revision'],)).fetchone()
                if row is not None:
                    if row != (raw, digest):
                        raise ValueError('same export revision has different received bytes')
                    created = False
                else:
                    connection.execute('INSERT INTO learning_evidence VALUES (?,?,?)',
                                       (value['revision'], raw, digest))
                    created = True
        return dict(created=created, export=value, authentication='not_verified',
                    scope='captured_metadata_only')

    def get(self, revision):
        with closing(self._connect()) as connection:
            connection.execute('BEGIN')
            self._validate_schema(connection)
            row = connection.execute('SELECT bundle,bundle_sha256 FROM learning_evidence '
                                     'WHERE revision=?', (revision,)).fetchone()
        if row is None:
            return None
        raw, digest = row
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('stored bundle hash differs')
        value = verify(unpack(raw), self.path.parent)
        if value['revision'] != revision:
            raise ValueError('stored revision differs')
        return dict(export=value, bundle_sha256=digest, authentication='not_verified',
                    scope='captured_metadata_only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--episode', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    result = LearningReceiver(args.database).ingest(args.export, args.episode, args.receipt)
    print(json.dumps(dict(revision=result['export']['revision'], created=result['created'],
                          authentication=result['authentication'], scope=result['scope'])))


if __name__ == '__main__':
    main()
