"""Manage the Windows Scheduled Task that runs `src.cli.scheduled_run` automatically.

These are plain functions meant for direct use (CLI, REPL, a future `schedule`
command) and are also wrapped as an orchestrator tool in
`src/orchestration/tools.py` so the agent can set, check, or remove the
schedule from a chat instruction.
"""
import re
import subprocess
from pathlib import Path

TASK_NAME = "AIInfluencerAgency_ScheduledPost"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

# Validated before it ever reaches PowerShell, since it's interpolated into a
# shell command string — this is the injection boundary, not just a format check.
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _run_powershell(script: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"powershell exited {result.returncode}")
    return result.stdout.strip()


def set_daily_schedule(time_str: str, task_name: str = TASK_NAME) -> str:
    """Create the scheduled task if it doesn't exist yet, or replace its trigger
    time if it does — Register-ScheduledTask -Force overwrites an existing
    task's definition wholesale, so create and update are the same call.

    `time_str` must be 24-hour "HH:MM" (e.g. "14:30" for 2:30 PM).
    """
    if not _TIME_RE.match(time_str):
        raise ValueError(f'time_str must be 24-hour "HH:MM", got {time_str!r}')

    script = f'''
    $action = New-ScheduledTaskAction -Execute "{PYTHON_EXE}" -Argument "-m src.cli.scheduled_run" -WorkingDirectory "{PROJECT_ROOT}"
    $trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date "{time_str}")
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
    Register-ScheduledTask -TaskName "{task_name}" -Action $action -Trigger $trigger -Settings $settings -Description "Runs src.cli.scheduled_run daily." -Force | Out-Null
    (Get-ScheduledTaskInfo -TaskName "{task_name}").NextRunTime
    '''
    next_run = _run_powershell(script)
    return f"Scheduled task '{task_name}' set to run daily at {time_str}. Next run: {next_run}"


def get_schedule_status(task_name: str = TASK_NAME) -> str:
    """Return the task's current state, next/last run time, and last result —
    or a clear "not found" message if it hasn't been created yet."""
    script = f'''
    $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction SilentlyContinue
    if (-not $task) {{ Write-Output "NOT_FOUND"; exit }}
    $info = Get-ScheduledTaskInfo -TaskName "{task_name}"
    Write-Output "State=$($task.State); NextRunTime=$($info.NextRunTime); LastRunTime=$($info.LastRunTime); LastTaskResult=$($info.LastTaskResult)"
    '''
    result = _run_powershell(script)
    return "No scheduled task exists yet." if result == "NOT_FOUND" else result


def delete_schedule(task_name: str = TASK_NAME) -> str:
    """Remove the scheduled task entirely. Reports as a no-op if it doesn't exist."""
    script = f'''
    $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction SilentlyContinue
    if (-not $task) {{ Write-Output "NOT_FOUND"; exit }}
    Unregister-ScheduledTask -TaskName "{task_name}" -Confirm:$false
    Write-Output "REMOVED"
    '''
    result = _run_powershell(script)
    if result == "NOT_FOUND":
        return f"No scheduled task named '{task_name}' exists — nothing to remove."
    return f"Scheduled task '{task_name}' removed."
