#!/usr/bin/env python3
"""
Auto-archive journal.md when it exceeds threshold.

Archives to: documents/archive/journals/journal_YYYYMMDD_HHMMSS.md
Preserves journal header in fresh journal.md

Usage:
    python3 .claude/skills/journal-tracker/scripts/archive-journal.py --dry-run
    python3 .claude/skills/journal-tracker/scripts/archive-journal.py
    python3 .claude/skills/journal-tracker/scripts/archive-journal.py --threshold 1000
    python3 .claude/skills/journal-tracker/scripts/archive-journal.py --force  # Archive regardless of threshold
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_THRESHOLD = 1500

JOURNAL_HEADER = """# Spoq Development Journal

This journal tracks all AI agent work sessions with timestamps, confidence scores, and detailed summaries. The journal system supports:

- **XAI (Explainable AI)**: Detailed logging for explainability and meta-orchestration
- **Multi-Agent Systems**: Track work from multiple agents and swarms
- **Knowledge Graph Integration**: Parse entries into database for work relationship analysis
- **Training Data**: Combine with git commits for LLM training on software development patterns
- **Auto-Archiving**: When journal exceeds 1500 lines, run `python3 .claude/skills/journal-tracker/scripts/archive-journal.py`
- **Hierarchical Task Decomposition**: Track how complex tasks are broken down and distributed

## Journal Format

Each entry includes:
- **Agent**: Name of AI assistant (Claude Code, Swarm Agent, etc.)
- **Timestamps**: Exact start/end times (UTC) using `python3 .claude/skills/journal-tracker/scripts/get-time.py`
- **Confidence**: 0.0-1.0 score for work quality and completeness
- **Session Type**: Category of work performed (development, refactor, bugfix, planning, etc.)
- **Files Modified**: Complete list of changed files
- **Tasks Completed/Total**: Progress tracking
- **Summary**: Brief overview of work accomplished
- **Details**: Comprehensive breakdown of changes, issues, testing, next steps

See `.claude/skills/journal-tracker/SKILL.md` for complete documentation and examples.

---
"""


def find_repo_root() -> Path:
    """Find repository root by looking for .git directory."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    # Fallback: assume standard skill location
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def extract_date_range(content: str) -> tuple[str | None, str | None]:
    """Extract earliest and latest dates from journal entries."""
    # Match ISO timestamps in frontmatter
    timestamps = re.findall(r"(?:start_time|end_time):\s*(\d{4}-\d{2}-\d{2})", content)
    if not timestamps:
        return None, None
    timestamps.sort()
    return timestamps[0], timestamps[-1]


def main():
    parser = argparse.ArgumentParser(description="Archive journal.md when it exceeds threshold")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check status without archiving",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Line count threshold for archiving (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Archive regardless of line count threshold",
    )
    args = parser.parse_args()

    repo_root = find_repo_root()
    journal_path = repo_root / "journal.md"
    archive_dir = repo_root / "documents" / "archive" / "journals"

    # Check journal exists
    if not journal_path.exists():
        print(f"Error: journal.md not found at {journal_path}")
        sys.exit(1)

    # Read and count lines
    content = journal_path.read_text(encoding='utf-8')
    line_count = len(content.splitlines())

    print(f"Journal: {journal_path}")
    print(f"Current lines: {line_count}")
    print(f"Threshold: {args.threshold}")

    if line_count < args.threshold and not args.force:
        print(f"\nNo archiving needed (below threshold of {args.threshold} lines)")
        if args.dry_run:
            print("Status: OK")
        sys.exit(0)

    # Extract date range for context
    start_date, end_date = extract_date_range(content)
    date_info = ""
    if start_date and end_date:
        date_info = f" (entries from {start_date} to {end_date})"

    if args.dry_run:
        print(f"\nWould archive {line_count} lines{date_info}")
        print(f"Archive directory: {archive_dir}")
        print("Run without --dry-run to archive")
        sys.exit(0)

    # Create archive directory
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Generate archive filename with timestamp
    now = datetime.now(timezone.utc)
    archive_name = f"journal_{now.strftime('%Y%m%d_%H%M%S')}.md"
    archive_path = archive_dir / archive_name

    # Write archive
    archive_path.write_text(content, encoding='utf-8')
    print(f"\nArchived to: {archive_path}")
    print(f"Lines archived: {line_count}{date_info}")

    # Reset journal with header
    journal_path.write_text(JOURNAL_HEADER, encoding='utf-8')
    new_line_count = len(JOURNAL_HEADER.splitlines())
    print(f"Reset journal.md ({new_line_count} lines)")

    print("\nArchive complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
