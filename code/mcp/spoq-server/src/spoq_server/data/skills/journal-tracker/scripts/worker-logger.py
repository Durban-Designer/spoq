#!/usr/bin/env python3
"""
Structured logging for headless worker agents.

Workers receive tasks from managers, execute them, and report structured results.
This creates training data for fine-tuning open-source models.

Usage (from worker script):
    worker = WorkerLogger(task_id="task-001", worker_type="implementation")
    worker.start(task_description="Implement user service", assigned_by="manager-1")
    worker.log_step("Reading existing code", tool="Read", file="user.service.ts")
    worker.log_step("Writing tests", tool="Write", file="user.service.spec.ts")
    worker.complete(success=True, confidence=0.92, output_files=["user.service.ts"])
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path

class WorkerLogger:
    def __init__(self, task_id, worker_type, worker_id=None):
        """
        Initialize worker logger.

        Args:
            task_id: Unique task identifier (from manager)
            worker_type: Type of worker (implementation, testing, integration, validation, documentation)
            worker_id: Unique worker identifier (defaults to env var or generated)
        """
        self.task_id = task_id
        self.worker_type = worker_type
        self.worker_id = worker_id or os.environ.get('WORKER_ID', f"worker-{os.getpid()}")

        # Session directory
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent.parent.parent
        self.session_dir = repo_root / "session-transcripts" / "workers" / task_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.execution_file = self.session_dir / f"{self.worker_id}.jsonl"
        self.result_file = self.session_dir / f"{self.worker_id}-result.json"

        self.start_time = None
        self.steps = []

    def get_timestamp(self):
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def start(self, task_description, assigned_by, context=None):
        """Start task execution."""
        self.start_time = self.get_timestamp()

        entry = {
            "event": "start",
            "timestamp": self.start_time,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "task_description": task_description,
            "assigned_by": assigned_by,
            "context": context or {}
        }

        self._append(entry)

    def log_step(self, description, tool=None, **kwargs):
        """Log execution step."""
        step = {
            "event": "step",
            "timestamp": self.get_timestamp(),
            "description": description,
            "tool": tool
        }
        step.update(kwargs)

        self.steps.append(step)
        self._append(step)

    def log_error(self, error_message, recovery_action=None):
        """Log error encountered."""
        entry = {
            "event": "error",
            "timestamp": self.get_timestamp(),
            "error": error_message,
            "recovery": recovery_action
        }
        self._append(entry)

    def complete(self, success, confidence, output_files=None, summary=None, issues=None):
        """Complete task and write result."""
        end_time = self.get_timestamp()

        # Calculate duration
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(end_time)
            duration_seconds = (end - start).total_seconds()
        else:
            duration_seconds = None

        # Write completion event
        completion = {
            "event": "complete",
            "timestamp": end_time,
            "success": success,
            "confidence": confidence,
            "duration_seconds": duration_seconds,
            "steps_count": len(self.steps)
        }
        self._append(completion)

        # Write result file
        result = {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "start_time": self.start_time,
            "end_time": end_time,
            "duration_seconds": duration_seconds,
            "success": success,
            "confidence": confidence,
            "output_files": output_files or [],
            "summary": summary,
            "issues": issues or [],
            "steps_count": len(self.steps)
        }

        with open(self.result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)

    def _append(self, entry):
        """Append entry to execution log."""
        with open(self.execution_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

def main():
    """CLI interface for worker logging."""
    import argparse

    parser = argparse.ArgumentParser(description='Worker logger CLI')
    parser.add_argument('--task-id', required=True, help='Task identifier')
    parser.add_argument('--worker-type', required=True, help='Worker type')
    parser.add_argument('--action', required=True, choices=['start', 'step', 'error', 'complete'])
    parser.add_argument('--description', help='Task or step description')
    parser.add_argument('--assigned-by', help='Manager ID (for start)')
    parser.add_argument('--tool', help='Tool used (for step)')
    parser.add_argument('--success', type=bool, help='Success flag (for complete)')
    parser.add_argument('--confidence', type=float, help='Confidence score (for complete)')
    parser.add_argument('--summary', help='Summary (for complete)')

    args = parser.parse_args()

    worker = WorkerLogger(args.task_id, args.worker_type)

    if args.action == 'start':
        worker.start(args.description, args.assigned_by)
    elif args.action == 'step':
        worker.log_step(args.description, tool=args.tool)
    elif args.action == 'error':
        worker.log_error(args.description)
    elif args.action == 'complete':
        worker.complete(args.success, args.confidence, summary=args.summary)

if __name__ == '__main__':
    main()
