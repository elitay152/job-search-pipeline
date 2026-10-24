import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

class Store:
    def __init__(self, path='local/pipeline.sqlite'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, manifest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(run_id TEXT, stage TEXT, payload TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, payload TEXT);
        ''')
        self.db.commit()

    def save(self, manifest):
        self.db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)', (manifest['id'], json.dumps(manifest)))
        self.db.commit()

    def event(self, run_id, stage, payload):
        self.db.execute('INSERT INTO events VALUES (?,?,?,?)', (run_id, stage, json.dumps(payload), now()))
        self.db.commit()

    def get(self, run_id):
        row = self.db.execute('SELECT manifest FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise ValueError('unknown run')
        return json.loads(row[0])

    def history(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT manifest FROM runs ORDER BY rowid DESC')]

    def career_snapshot(self, run_id):
        from .models import Career
        row = self.db.execute("SELECT payload FROM events WHERE run_id=? AND stage='inputs' ORDER BY rowid LIMIT 1", (run_id,)).fetchone()
        if not row:
            raise ValueError('Run input snapshot unavailable')
        return Career.model_validate(json.loads(row[0])['career'])

    def follow_up_answers(self, input_hash):
        rows = self.db.execute("SELECT payload FROM events WHERE run_id=? AND stage='follow_up' ORDER BY rowid", ('intake-' + input_hash,))
        return {value['requirement_id']: value for value in (json.loads(row[0]) for row in rows)}
