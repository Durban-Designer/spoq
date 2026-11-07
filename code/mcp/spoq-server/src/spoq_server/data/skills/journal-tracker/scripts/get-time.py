#!/usr/bin/env python3
"""
Get current system time in ISO 8601 format for journal entries.

Usage:
    python get-time.py              # Current time
    python get-time.py --format iso # ISO 8601 (default)
    python get-time.py --format unix # Unix timestamp
"""

import sys
from datetime import datetime, timezone

def get_current_time(format_type='iso'):
    """Get current time in specified format."""
    now = datetime.now(timezone.utc)

    if format_type == 'iso':
        # ISO 8601 format: 2025-11-01T10:52:34Z
        return now.strftime('%Y-%m-%dT%H:%M:%SZ')
    elif format_type == 'unix':
        # Unix timestamp
        return str(int(now.timestamp()))
    elif format_type == 'readable':
        # Human readable: 2025-11-01 10:52:34 UTC
        return now.strftime('%Y-%m-%d %H:%M:%S UTC')
    else:
        return now.strftime('%Y-%m-%dT%H:%M:%SZ')

if __name__ == '__main__':
    format_type = 'iso'

    if len(sys.argv) > 1:
        if sys.argv[1] == '--format' and len(sys.argv) > 2:
            format_type = sys.argv[2]
        elif sys.argv[1] in ['--help', '-h']:
            print(__doc__)
            sys.exit(0)

    print(get_current_time(format_type))
