#!/usr/bin/env python3
"""
Auto-capture Claude Code interactive sessions for XAI and training data.

This script is designed to be called from Claude Code hooks to automatically
log all interactions, tool calls, and reasoning for manager agents.

Usage (from hooks):
    python3 session-logger.py --event prompt --content "..."
    python3 session-logger.py --event response --content "..."
    python3 session-logger.py --event tool-call --tool Read --params '{"file_path": "..."}'
    python3 session-logger.py --event session-end
"""

import os
import sys
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

class SessionLogger:
    def __init__(self, session_dir):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.transcript_file = self.session_dir / "transcript.jsonl"
        self.tool_calls_file = self.session_dir / "tool-calls.jsonl"
        self.thinking_file = self.session_dir / "thinking.jsonl"
        self.metadata_file = self.session_dir / "metadata.json"

    def get_timestamp(self):
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def append_jsonl(self, file_path, data):
        """Append JSON line to file."""
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')

    def log_prompt(self, content, tokens=None):
        """Log user prompt."""
        entry = {
            "timestamp": self.get_timestamp(),
            "role": "user",
            "content": content,
            "tokens": tokens
        }
        self.append_jsonl(self.transcript_file, entry)

    def log_response(self, content, tokens=None, thinking=None):
        """Log assistant response."""
        entry = {
            "timestamp": self.get_timestamp(),
            "role": "assistant",
            "content": content,
            "tokens": tokens
        }
        self.append_jsonl(self.transcript_file, entry)

        # Log thinking separately if present
        if thinking:
            thinking_entry = {
                "timestamp": self.get_timestamp(),
                "content": thinking,
                "tokens": len(thinking) // 4  # Rough estimate
            }
            self.append_jsonl(self.thinking_file, thinking_entry)

    def log_tool_call(self, tool_name, params, result=None, duration_ms=None, success=True):
        """Log tool invocation."""
        entry = {
            "timestamp": self.get_timestamp(),
            "tool": tool_name,
            "params": params,
            "success": success,
            "duration_ms": duration_ms
        }

        if result:
            # Hash large results to save space
            if isinstance(result, str) and len(result) > 1000:
                entry["result_hash"] = hashlib.sha256(result.encode()).hexdigest()
                entry["result_size"] = len(result)
            else:
                entry["result"] = result

        self.append_jsonl(self.tool_calls_file, entry)

    def update_metadata(self, **kwargs):
        """Update session metadata."""
        metadata = {}
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

        metadata.update(kwargs)

        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dumps(metadata, f, indent=2)

    def finalize_session(self, summary=None, confidence=None):
        """Finalize session with summary."""
        # Calculate statistics
        transcript_lines = 0
        tool_calls = 0

        if self.transcript_file.exists():
            with open(self.transcript_file, 'r', encoding='utf-8') as f:
                transcript_lines = sum(1 for _ in f)

        if self.tool_calls_file.exists():
            with open(self.tool_calls_file, 'r', encoding='utf-8') as f:
                tool_calls = sum(1 for _ in f)

        metadata = {
            "agent": "Claude Code Manager",
            "agent_mode": "interactive",
            "end_time": self.get_timestamp(),
            "transcript_messages": transcript_lines,
            "tool_calls_count": tool_calls,
            "summary": summary,
            "confidence": confidence
        }

        self.update_metadata(**metadata)

def get_session_dir():
    """Get or create current session directory."""
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent.parent
    sessions_dir = repo_root / "session-transcripts"

    # Use environment variable for session ID (set by manager)
    session_id = os.environ.get('CLAUDE_SESSION_ID')

    if not session_id:
        # Create new session
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')
        session_id = f"manager-{timestamp}"

    return sessions_dir / session_id

def main():
    event = None
    content = None
    tool_name = None
    params = None

    # Parse arguments
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--event':
            event = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--content':
            content = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--tool':
            tool_name = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--params':
            params = json.loads(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    session_dir = get_session_dir()
    logger = SessionLogger(session_dir)

    # Handle event
    if event == 'prompt':
        logger.log_prompt(content)
    elif event == 'response':
        logger.log_response(content)
    elif event == 'tool-call':
        logger.log_tool_call(tool_name, params)
    elif event == 'session-end':
        logger.finalize_session()
    else:
        print(f"Unknown event: {event}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
