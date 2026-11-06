"""Dashboard closing must preserve in-flight work and queued completion."""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from gui.lab_dashboard import LabDashboardWindow


class WorkerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = LabDashboardWindow(preferences={})
        self.window.show()
        self.app.processEvents()
        self.release_task = threading.Event()
        errors = patch.object(self.window, "_error")
        self.error = errors.start()
        self.addCleanup(errors.stop)
        self.addCleanup(self.finish_task)

    def finish_task(self):
        self.release_task.set()
        if self.window.worker is not None:
            self.window.worker.wait(5000)
        self.app.processEvents()
        self.window.close()

    def wait_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail("Timed out waiting for task completion")
            time.sleep(.002)

    def test_idle_window_can_close(self):
        self.assertTrue(self.window.close())
        self.assertFalse(self.window.isVisible())

    def test_close_keeps_running_task_alive_until_result_is_delivered(self):
        started = threading.Event()
        delivered = Mock()

        def task():
            started.set()
            if not self.release_task.wait(5):
                raise RuntimeError("Test task was not released")
            return "saved result"

        self.window._run_worker("Saving results", task, delivered)
        self.assertTrue(started.wait(5))
        worker = self.window.worker
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        self.assertTrue(worker.isRunning())
        self.assertIn("finish", self.window.status.currentMessage().lower())
        delivered.assert_not_called()

        self.release_task.set()
        self.wait_until(lambda: self.window.worker is None)
        delivered.assert_called_once_with("saved result")
        self.assertFalse(self.window._busy)
        self.assertTrue(self.window.close())

    def test_close_waits_for_queued_completion_after_thread_stops(self):
        delivered = Mock()
        self.window._run_worker("Finishing results", lambda: "ready", delivered)
        self.assertTrue(self.window.worker.wait(5000))
        # Do not pump the event loop yet: the result still belongs to the GUI.
        self.assertFalse(self.window.worker.isRunning())
        delivered.assert_not_called()
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.isVisible())
        self.wait_until(lambda: self.window.worker is None)
        delivered.assert_called_once_with("ready")
        self.assertTrue(self.window.close())

    def test_failed_task_restores_normal_close(self):
        def fail():
            self.release_task.wait(5)
            raise ValueError("Cannot save results")

        with self.assertLogs("laserlab.gui", level="ERROR"):
            self.window._run_worker("Saving results", fail, Mock())
            self.assertFalse(self.window.close())
            self.release_task.set()
            self.wait_until(lambda: self.window.worker is None)
        self.error.assert_called_once_with("Cannot save results")
        self.assertFalse(self.window._busy)
        self.assertTrue(self.window.close())


if __name__ == "__main__":
    unittest.main()
