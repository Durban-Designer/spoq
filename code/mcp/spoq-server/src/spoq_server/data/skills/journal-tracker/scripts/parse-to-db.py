#!/usr/bin/env python3
"""
Parse journal entries into database for analysis and knowledge graph construction.

Usage:
    python3 parse-to-db.py --db journal.db                    # SQLite
    python3 parse-to-db.py --db journal.db --source mega-journal.md
    python3 parse-to-db.py --analyze                          # Generate statistics
"""

import os
import sys
import yaml
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

def extract_yaml_entries(file_path):
    """Extract YAML frontmatter entries from journal."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    entries = []
    parts = content.split('---')

    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break

        yaml_part = parts[i].strip()
        markdown_part = parts[i + 1].strip()

        try:
            # Parse YAML
            data = yaml.safe_load(yaml_part)

            # Add markdown content
            data['markdown_content'] = markdown_part

            # Extract sections from markdown
            sections = parse_markdown_sections(markdown_part)
            data['sections'] = sections

            entries.append(data)
        except yaml.YAMLError as e:
            print(f"YAML parse error: {e}")
            continue

    return entries

def parse_markdown_sections(markdown):
    """Parse markdown into structured sections."""
    sections = {}
    current_section = None
    current_content = []

    for line in markdown.split('\n'):
        if line.startswith('## '):
            # Save previous section
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()

            # Start new section
            current_section = line[3:].strip()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_section:
        sections[current_section] = '\n'.join(current_content).strip()

    return sections

def create_database(db_path):
    """Create SQLite database schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Journal entries table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration_seconds INTEGER,
            confidence REAL NOT NULL,
            session_type TEXT NOT NULL,
            tasks_completed INTEGER,
            tasks_total INTEGER,
            summary TEXT,
            work_completed TEXT,
            changes_made TEXT,
            issues_encountered TEXT,
            testing TEXT,
            next_steps TEXT,
            notes TEXT,
            markdown_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Files modified table (many-to-many)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files_modified (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES journal_entries(id)
        )
    ''')

    # Indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_start_time ON journal_entries(start_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_session_type ON journal_entries(session_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_confidence ON journal_entries(confidence)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON files_modified(file_path)')

    conn.commit()
    return conn

def calculate_duration(start_time, end_time):
    """Calculate duration in seconds between timestamps."""
    try:
        start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        return int((end - start).total_seconds())
    except:
        return None

def insert_entry(conn, entry):
    """Insert journal entry into database."""
    cursor = conn.cursor()

    # Calculate duration
    duration = calculate_duration(entry.get('start_time', ''), entry.get('end_time', ''))

    # Extract sections
    sections = entry.get('sections', {})

    # Insert main entry
    cursor.execute('''
        INSERT INTO journal_entries (
            agent, start_time, end_time, duration_seconds, confidence,
            session_type, tasks_completed, tasks_total,
            summary, work_completed, changes_made, issues_encountered,
            testing, next_steps, notes, markdown_content
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        entry.get('agent', 'Unknown'),
        entry.get('start_time', ''),
        entry.get('end_time', ''),
        duration,
        entry.get('confidence', 0.0),
        entry.get('session_type', 'unknown'),
        entry.get('tasks_completed', 0),
        entry.get('tasks_total', 0),
        sections.get('Summary', ''),
        sections.get('Work Completed', ''),
        sections.get('Changes Made', ''),
        sections.get('Issues Encountered', ''),
        sections.get('Testing', ''),
        sections.get('Next Steps', ''),
        sections.get('Notes', ''),
        entry.get('markdown_content', '')
    ))

    entry_id = cursor.lastrowid

    # Insert files modified
    files = entry.get('files_modified', [])
    for file_path in files:
        cursor.execute('''
            INSERT INTO files_modified (entry_id, file_path)
            VALUES (?, ?)
        ''', (entry_id, file_path))

    conn.commit()
    return entry_id

def generate_statistics(conn):
    """Generate statistics from journal database."""
    cursor = conn.cursor()

    print("\n=== Journal Statistics ===\n")

    # Total entries
    cursor.execute('SELECT COUNT(*) FROM journal_entries')
    total = cursor.fetchone()[0]
    print(f"Total Entries: {total}")

    # By session type
    cursor.execute('''
        SELECT session_type, COUNT(*), AVG(confidence)
        FROM journal_entries
        GROUP BY session_type
        ORDER BY COUNT(*) DESC
    ''')
    print("\nBy Session Type:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} sessions (avg confidence: {row[2]:.2f})")

    # Total duration
    cursor.execute('SELECT SUM(duration_seconds) FROM journal_entries')
    total_seconds = cursor.fetchone()[0] or 0
    hours = total_seconds / 3600
    print(f"\nTotal Development Time: {hours:.1f} hours")

    # Confidence distribution
    cursor.execute('''
        SELECT
            CASE
                WHEN confidence >= 0.95 THEN '0.95-1.0 (Very High)'
                WHEN confidence >= 0.85 THEN '0.85-0.94 (High)'
                WHEN confidence >= 0.75 THEN '0.75-0.84 (Good)'
                WHEN confidence >= 0.65 THEN '0.65-0.74 (Moderate)'
                ELSE '<0.65 (Low)'
            END as range,
            COUNT(*)
        FROM journal_entries
        GROUP BY range
        ORDER BY range DESC
    ''')
    print("\nConfidence Distribution:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} sessions")

    # Most modified files
    cursor.execute('''
        SELECT file_path, COUNT(*) as mod_count
        FROM files_modified
        GROUP BY file_path
        ORDER BY mod_count DESC
        LIMIT 10
    ''')
    print("\nMost Modified Files:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} times")

    # Agent activity
    cursor.execute('''
        SELECT agent, COUNT(*), SUM(duration_seconds)/3600 as hours
        FROM journal_entries
        GROUP BY agent
        ORDER BY COUNT(*) DESC
    ''')
    print("\nAgent Activity:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} sessions ({row[2]:.1f} hours)")

def main():
    # Parse arguments
    db_path = 'journal.db'
    source_file = 'journal.md'
    analyze = '--analyze' in sys.argv

    if '--db' in sys.argv:
        idx = sys.argv.index('--db')
        if idx + 1 < len(sys.argv):
            db_path = sys.argv[idx + 1]

    if '--source' in sys.argv:
        idx = sys.argv.index('--source')
        if idx + 1 < len(sys.argv):
            source_file = sys.argv[idx + 1]

    # Determine paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent.parent
    db_full_path = repo_root / db_path
    source_full_path = repo_root / source_file

    # Create database
    print(f"Database: {db_full_path}")
    conn = create_database(str(db_full_path))

    if not analyze:
        # Parse journal
        print(f"Parsing: {source_full_path}")
        entries = extract_yaml_entries(str(source_full_path))
        print(f"Found {len(entries)} entries")

        # Insert entries
        for i, entry in enumerate(entries, 1):
            entry_id = insert_entry(conn, entry)
            print(f"Inserted entry {i}/{len(entries)} (ID: {entry_id})")

    # Generate statistics
    generate_statistics(conn)

    conn.close()
    print(f"\nDatabase created: {db_full_path}")

if __name__ == '__main__':
    main()
