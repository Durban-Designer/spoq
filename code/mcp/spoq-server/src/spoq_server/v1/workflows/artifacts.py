"""Immutable, bounded, registered text artifacts; references never replace content."""
from __future__ import annotations

import hashlib
import json

from ..db import now, transaction, uid
from .repository import WorkflowRepository
from .types import canonical_json, identifier

MAX_CONTENT_BYTES = 1024 * 1024


def text(value, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{label} requires nonempty text of at most {maximum} characters')
    return value


def parse_artifact(row) -> dict:
    result = dict(row)
    result['metadata'] = json.loads(result['metadata'])
    return result


class ArtifactRepository:
    def __init__(self, repository: WorkflowRepository):
        self.repository = repository
        self.path = repository.path

    @staticmethod
    def add(db, run_id: str, attempt_id: str, kind: str, content: str | bytes,
            author: str, source: str = 'agent', metadata: dict | None = None,
            artifact_id: str | None = None) -> dict:
        identifier(kind, 'artifact kind')
        text(author, 'Artifact author')
        identifier(source, 'artifact source')
        if isinstance(content, bytes):
            try:
                content = content.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise ValueError('Artifacts require UTF-8 text') from exc
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > MAX_CONTENT_BYTES:
            raise ValueError('Artifacts require nonempty UTF-8 content of at most one MiB; a reference alone is not content')
        metadata = metadata if metadata is not None else {}
        if not isinstance(metadata, dict):
            raise ValueError('Artifact metadata must be a JSON object')
        metadata_json = canonical_json(metadata)
        run = WorkflowRepository._get(db, run_id)
        if run['status'] == 'legacy_unclassified':
            raise ValueError('Artifacts require a classified workflow run')
        attempt = db.execute('SELECT * FROM workflow_attempts WHERE id=? AND run_id=?', (attempt_id, run_id)).fetchone()
        if attempt is None:
            raise ValueError('Artifact attempt must belong to the same workflow run')
        artifact_id = artifact_id or uid()
        identifier(artifact_id, 'artifact ID')
        digest = hashlib.sha256(content.encode()).hexdigest()
        db.execute('INSERT INTO workflow_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (artifact_id, run_id, attempt_id, run['scope_id'], kind, author, source,
                    content, digest, metadata_json, now()))
        return parse_artifact(db.execute('SELECT * FROM workflow_artifacts WHERE id=?', (artifact_id,)).fetchone())

    def get(self, artifact_id: str, *, run_id: str | None = None) -> dict:
        with transaction(self.path) as db:
            row = db.execute('SELECT * FROM workflow_artifacts WHERE id=?', (artifact_id,)).fetchone()
            if row is None or run_id is not None and row['run_id'] != run_id:
                raise ValueError('Unknown artifact in this workflow run')
            return parse_artifact(row)

    def list(self, run_id: str, *, limit: int = 100, after: str = '', include_content: bool = False) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError('Artifact list limit must be 1–500')
        with transaction(self.path) as db:
            WorkflowRepository._get(db, run_id)
            columns = ('*' if include_content else
                       'id,run_id,attempt_id,scope_id,kind,author,source,sha256,metadata,created_at,'
                       'length(CAST(content AS BLOB)) AS content_bytes')
            rows = db.execute(f'SELECT {columns} FROM workflow_artifacts WHERE run_id=? AND id>? ORDER BY id LIMIT ?',
                              (run_id, after, limit)).fetchall()
            return [parse_artifact(row) for row in rows]

    def register(self, run_id: str, attempt_id: str, kind: str, content: str, author: str,
                 *, key: str, expected_revision: int, source: str = 'agent', metadata: dict | None = None, actor: str = 'orchestrator') -> dict:
        request = {'operation': 'artifact', 'attempt_id': attempt_id, 'kind': kind, 'content': content,
                   'author': author, 'source': source, 'metadata': metadata}
        def operation(db, current):
            row = self.add(db, run_id, attempt_id, kind, content, author, source, metadata)
            return {'state': current['state'], 'status': current['status'], 'event_kind': 'artifact_registered',
                    'payload': {'artifact_id': row['id'], 'sha256': row['sha256'], 'kind': kind}, 'result': row}
        return self.repository.mutate(run_id, key, expected_revision, actor, operation, request=request)
