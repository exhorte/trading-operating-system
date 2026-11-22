"""The only module of the launcher that ends a process (ADR 0038, § 3 and § 5).

It does not decide *which* process: the caller hands it a pid the registry owns, proven by pid and creation time (``stopper.py``). Two things
only: ask politely — a console **Ctrl+Break**, which uvicorn turns into an orderly shutdown (workers included, ADR 0037) — and end a whole tree.

How the polite request works, as measured on this machine: a Windows signal travels through a console, and a process can only signal the console
it is attached to, so a short-lived helper detaches from its own console, attaches to the target's and sends Ctrl+Break **to the target's process
group — the group whose id is the target's pid**. That is why ``actions.SubprocessSpawner`` starts the core as the leader of its own group: the
event then reaches that group only, never the helper itself (sent to the whole console, the helper died of its own signal). Ctrl+Break rather
than Ctrl+C because a process may have Ctrl+C switched off — the switch is inherited — and Ctrl+Break cannot be switched off. A program that does not
handle it is ended by it, which is a stop like any other.

A process the launcher did not start (adopted) is not a group leader: the request is refused by Windows, ``request_stop`` says so, and the caller
ends it by force after saying that no polite stop was possible.
"""

from __future__ import annotations

import sys

from trading_os.launcher.ports import CommandRunner

TASKKILL_NOT_FOUND = 128  # taskkill's code for « no such process »: already gone is the goal reached

# Run with ``python -c`` and the target pid as argument. Exit 0 = the event was sent to the target's group.
CTRL_BREAK_HELPER = """
import ctypes, sys, time
kernel = ctypes.windll.kernel32
kernel.FreeConsole()
if not kernel.AttachConsole(int(sys.argv[1])):
    sys.exit(2)
sent = kernel.GenerateConsoleCtrlEvent(1, int(sys.argv[1]))  # CTRL_BREAK_EVENT, to the group led by the target
time.sleep(0.5)  # the event is delivered by another thread: leave the console only once it has gone through
kernel.FreeConsole()
sys.exit(0 if sent else 3)
"""


# Run with ``python -c`` and the target pid as argument. Exit 0 = at least one window of the process was asked to close (WM_CLOSE).
WINDOW_CLOSE_HELPER = """
import ctypes, sys
from ctypes import wintypes
user32 = ctypes.windll.user32
target = int(sys.argv[1])
asked = []
@ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
def visit(hwnd, _lparam):
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    if owner.value == target and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # top-level, visible, not owned by another window
        if user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE: what the close button sends
            asked.append(hwnd)
    return True
user32.EnumWindows(visit, 0)
sys.exit(0 if asked else 2)
"""


class WindowsProcessController:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def request_stop(self, pid: int) -> bool:
        result = self._runner.run([sys.executable, "-c", CTRL_BREAK_HELPER, str(int(pid))], timeout=20)
        return result.returncode == 0

    def request_window_close(self, pid: int) -> bool:
        result = self._runner.run([sys.executable, "-c", WINDOW_CLOSE_HELPER, str(int(pid))], timeout=20)
        return result.returncode == 0

    def terminate_tree(self, pid: int) -> bool:
        result = self._runner.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], timeout=30)
        return result.returncode in {0, TASKKILL_NOT_FOUND}
