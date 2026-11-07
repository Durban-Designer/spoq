#!/usr/bin/env python3
"""
Aggregate manager and worker sessions into hierarchical view for training data.

This script combines:
- Manager conversation (task decomposition, decision-making)
- Worker execution traces (implementation details)
- Results and outcomes (success rates, quality metrics)

Output is training data suitable for fine-tuning open-source models.

Usage:
    python3 aggregate-sessions.py --session manager-2025-11-01T14-00-00Z
    python3 aggregate-sessions.py --date 2025-11-01 --output training-data.jsonl
    python3 aggregate-sessions.py --all --format training
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

class SessionAggregator:
    def __init__(self, sessions_dir):
        self.sessions_dir = Path(sessions_dir)

    def load_manager_session(self, session_id):
        """Load manager interactive session."""
        session_dir = self.sessions_dir / session_id

        if not session_dir.exists():
            return None

        session = {
            "session_id": session_id,
            "type": "manager",
            "transcript": [],
            "tool_calls": [],
            "thinking": [],
            "metadata": {}
        }

        # Load transcript
        transcript_file = session_dir / "transcript.jsonl"
        if transcript_file.exists():
            with open(transcript_file, 'r', encoding='utf-8') as f:
                for line in f:
                    session["transcript"].append(json.loads(line))

        # Load tool calls
        tool_calls_file = session_dir / "tool-calls.jsonl"
        if tool_calls_file.exists():
            with open(tool_calls_file, 'r', encoding='utf-8') as f:
                for line in f:
                    session["tool_calls"].append(json.loads(line))

        # Load thinking
        thinking_file = session_dir / "thinking.jsonl"
        if thinking_file.exists():
            with open(thinking_file, 'r', encoding='utf-8') as f:
                for line in f:
                    session["thinking"].append(json.loads(line))

        # Load metadata
        metadata_file = session_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                session["metadata"] = json.load(f)

        return session

    def load_worker_sessions(self, task_id):
        """Load all worker sessions for a task."""
        workers_dir = self.sessions_dir / "workers" / task_id

        if not workers_dir.exists():
            return []

        workers = []

        for worker_file in workers_dir.glob("worker-*-result.json"):
            with open(worker_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            # Load execution trace
            worker_id = result["worker_id"]
            execution_file = workers_dir / f"{worker_id}.jsonl"
            execution = []

            if execution_file.exists():
                with open(execution_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        execution.append(json.loads(line))

            workers.append({
                "result": result,
                "execution": execution
            })

        return workers

    def extract_task_dispatches(self, manager_session):
        """Extract task dispatches from manager conversation."""
        tasks = []

        # Look for task dispatch patterns in transcript
        for msg in manager_session.get("transcript", []):
            if msg["role"] == "assistant":
                content = msg["content"].lower()

                # Simple pattern matching (can be enhanced)
                if "dispatch" in content or "assign" in content or "worker" in content:
                    tasks.append({
                        "timestamp": msg["timestamp"],
                        "content": msg["content"]
                    })

        return tasks

    def create_training_example(self, manager_session, worker_sessions):
        """Create training example from manager + worker sessions."""

        # Extract key components
        tasks_dispatched = self.extract_task_dispatches(manager_session)

        return {
            "session_id": manager_session["session_id"],
            "manager": {
                "conversation_length": len(manager_session.get("transcript", [])),
                "tool_calls": len(manager_session.get("tool_calls", [])),
                "thinking_blocks": len(manager_session.get("thinking", [])),
                "tasks_dispatched": len(tasks_dispatched),
                "metadata": manager_session.get("metadata", {})
            },
            "workers": [
                {
                    "worker_id": w["result"]["worker_id"],
                    "worker_type": w["result"]["worker_type"],
                    "duration": w["result"].get("duration_seconds"),
                    "success": w["result"]["success"],
                    "confidence": w["result"]["confidence"],
                    "steps": w["result"].get("steps_count", 0)
                }
                for w in worker_sessions
            ],
            "summary": {
                "total_workers": len(worker_sessions),
                "successful_workers": sum(1 for w in worker_sessions if w["result"]["success"]),
                "avg_confidence": sum(w["result"]["confidence"] for w in worker_sessions) / len(worker_sessions) if worker_sessions else 0,
                "total_duration": sum(w["result"].get("duration_seconds", 0) for w in worker_sessions)
            }
        }

    def aggregate_by_date(self, date_str):
        """Aggregate all sessions for a given date."""
        results = []

        # Find all manager sessions for date
        for session_dir in self.sessions_dir.glob(f"manager-{date_str}*"):
            session_id = session_dir.name
            manager_session = self.load_manager_session(session_id)

            if not manager_session:
                continue

            # Find associated worker sessions
            # (In real implementation, link via task IDs in manager conversation)
            worker_sessions = []

            example = self.create_training_example(manager_session, worker_sessions)
            results.append(example)

        return results

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Aggregate sessions for training data')
    parser.add_argument('--session', help='Specific manager session ID')
    parser.add_argument('--date', help='Date to aggregate (YYYY-MM-DD)')
    parser.add_argument('--all', action='store_true', help='Aggregate all sessions')
    parser.add_argument('--output', default='training-data.jsonl', help='Output file')
    parser.add_argument('--format', default='training', choices=['training', 'analysis'], help='Output format')

    args = parser.parse_args()

    # Determine sessions directory
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent.parent
    sessions_dir = repo_root / "session-transcripts"

    aggregator = SessionAggregator(sessions_dir)

    results = []

    if args.session:
        manager = aggregator.load_manager_session(args.session)
        if manager:
            workers = []  # Would load associated workers
            results.append(aggregator.create_training_example(manager, workers))
    elif args.date:
        results = aggregator.aggregate_by_date(args.date)
    elif args.all:
        # Aggregate all sessions
        for session_dir in sessions_dir.glob("manager-*"):
            session_id = session_dir.name
            manager = aggregator.load_manager_session(session_id)
            if manager:
                workers = []
                results.append(aggregator.create_training_example(manager, workers))

    # Write output
    output_path = repo_root / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(json.dumps(result) + '\n')

    print(f"Aggregated {len(results)} sessions to {output_path}")

if __name__ == '__main__':
    main()
