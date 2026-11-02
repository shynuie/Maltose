"""Verify an imported installation without printing user data or credentials."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tomllib

from maltose.migration import AgentMigration
from maltose.knowledge.parsers import ParserRegistry, MarkdownParser, TextParser, PDFParser
from maltose.knowledge.repositories import MetadataRepository
from maltose.knowledge.source_reader import SourceReader


def sql_rows(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok': raise RuntimeError('SQLite integrity check failed')
        tables = [row[0] for row in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        output = {}
        for table in tables:
            name = '"' + table.replace('"', '""') + '"'
            columns = [row[1] for row in db.execute('pragma table_info(' + name + ')')]
            output[table] = [dict(zip(columns, row)) for row in db.execute('select * from ' + name)]
        return output


def verify(destination: Path):
    receipt = json.loads((destination / 'migrations/agent-import-v1.json').read_text())
    if receipt['phase'] != 'complete': raise RuntimeError('Migration has not completed')
    backup = destination / 'migrations' / receipt['attempt'] / 'backup'
    mapper = AgentMigration(Path(receipt['source']), destination, Path(receipt['project']), legacy_root=Path(receipt['legacyRoot']))
    databases, total_rows = 0, 0
    for original in (backup / 'data').rglob('*'):
        if not original.is_file(): continue
        with original.open('rb') as stream: header = stream.read(16)
        if header != b'SQLite format 3\x00': continue
        relative = original.relative_to(backup)
        expected = sql_rows(original)
        actual = sql_rows(destination / relative)
        if str(relative) in receipt['databasePathUpdates']:
            for table, rows in expected.items():
                if table in {'documents', 'indexing_jobs'}:
                    for row in rows: row['path'] = mapper._mapped_path(row['path'])
        canonical = lambda rows: sorted((repr(row) for row in rows))
        if set(expected) != set(actual) or any(canonical(expected[table]) != canonical(actual[table]) for table in expected):
            raise RuntimeError('SQLite rows changed beyond the declared path migration')
        databases += 1; total_rows += sum(map(len, actual.values()))
    import lancedb
    lance_tables, lance_rows = 0, 0
    for original in (backup / 'data').rglob('*.lancedb'):
        if not original.is_dir(): continue
        current = destination / original.relative_to(backup)
        old, new = lancedb.connect(str(original)), lancedb.connect(str(current))
        names = set(old.list_tables().tables)
        if names != set(new.list_tables().tables): raise RuntimeError('LanceDB tables differ from backup')
        for name in names:
            left, right = old.open_table(name), new.open_table(name)
            serialize = lambda table: sorted(json.dumps(row, sort_keys=True, default=str) for row in table.to_arrow().to_pylist())
            if left.schema != right.schema or serialize(left) != serialize(right): raise RuntimeError('LanceDB records changed during migration')
            lance_tables += 1; lance_rows += right.count_rows()
    config = tomllib.loads((destination / 'maltose.toml').read_text())
    knowledge = config.get('knowledge', {})
    documents_verified = 0
    metadata_path = Path(knowledge.get('metadata', destination / 'data/knowledge/metadata.sqlite3'))
    if metadata_path.exists():
        metadata = MetadataRepository(metadata_path)
        try:
            reader = SourceReader(metadata=metadata, documents_root=knowledge['documents_root'], parsers=ParserRegistry([TextParser(), MarkdownParser(), PDFParser()]))
            for record in metadata.list_documents():
                if record['status'] == 'deleted': continue
                path = Path(record['path'])
                with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != record['content_hash']: raise RuntimeError('Source document content differs from its index')
                reader.read(record['id'])
                documents_verified += 1
        finally: metadata.close()
    return {'sqliteDatabases': databases, 'sqliteRowsPreserved': total_rows, 'lanceTables': lance_tables,
            'lanceRowsPreserved': lance_rows, 'sourceDocumentsReadAndHashVerified': documents_verified}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.destination.resolve())))
