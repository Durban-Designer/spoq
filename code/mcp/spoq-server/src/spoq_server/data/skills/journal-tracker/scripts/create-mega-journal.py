#!/usr/bin/env python3
"""
Consolidate all journal archives into a single mega journal.

Usage:
    python3 create-mega-journal.py                    # Create mega-journal.md
    python3 create-mega-journal.py --output custom.md # Custom output path
    python3 create-mega-journal.py --include-active   # Include current journal.md
"""

import os
import sys
from pathlib import Path
from datetime import datetime

def extract_entries(file_path):
    """
    Extract all entries from a journal file.
    Returns list of (timestamp, content) tuples.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    entries = []
    parts = content.split('---')

    # Skip header (first part before any ---)
    for i in range(1, len(parts), 2):
        if i + 1 >= len(parts):
            break

        yaml_part = parts[i].strip()
        markdown_part = parts[i + 1].strip() if i + 1 < len(parts) else ''

        # Extract timestamp from YAML
        timestamp = None
        for line in yaml_part.split('\n'):
            if line.startswith('start_time:'):
                timestamp = line.split(':', 1)[1].strip()
                break

        if timestamp:
            full_entry = f"---\n{yaml_part}\n---\n\n{markdown_part}\n\n---\n"
            entries.append((timestamp, full_entry))

    return entries

def create_mega_journal(archive_dir, output_path, include_active=False, journal_path=None):
    """
    Consolidate all archives into mega journal.
    """
    # Collect all archive files
    archive_files = []
    if os.path.exists(archive_dir):
        for filename in os.listdir(archive_dir):
            if filename.startswith('journal-') and filename.endswith('.md'):
                archive_files.append(os.path.join(archive_dir, filename))

    # Optionally include active journal
    if include_active and journal_path and os.path.exists(journal_path):
        archive_files.append(journal_path)

    if not archive_files:
        print("No journal files found")
        return False

    print(f"Found {len(archive_files)} journal files")

    # Extract all entries
    all_entries = []
    for file_path in archive_files:
        print(f"Processing: {os.path.basename(file_path)}")
        entries = extract_entries(file_path)
        all_entries.extend(entries)

    # Sort by timestamp
    all_entries.sort(key=lambda x: x[0])

    print(f"Total entries: {len(all_entries)}")

    # Create mega journal header
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    header = f"""# Wyrd Mega Journal

Consolidated journal containing all development sessions.

**Generated**: {now}
**Total Entries**: {len(all_entries)}
**Source Files**: {len(archive_files)}

This mega journal combines all archived journal files for:
- Historical analysis and pattern recognition
- LLM training data generation
- Knowledge graph construction
- Project reporting and XAI analysis

---

"""

    # Write mega journal
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(header)
        for timestamp, entry in all_entries:
            f.write(entry)
            f.write('\n')

    print(f"Mega journal created: {output_path}")
    print(f"Total size: {os.path.getsize(output_path):,} bytes")

    return True

def main():
    # Parse arguments
    output_path = 'mega-journal.md'
    include_active = '--include-active' in sys.argv

    if '--output' in sys.argv:
        idx = sys.argv.index('--output')
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    # Determine paths
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent.parent
    archive_dir = repo_root / 'journal-archives'
    journal_path = repo_root / 'journal.md'
    output_full_path = repo_root / output_path

    # Create mega journal
    success = create_mega_journal(
        str(archive_dir),
        str(output_full_path),
        include_active=include_active,
        journal_path=str(journal_path)
    )

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
