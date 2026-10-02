"""System tool contracts tested with stable measurements, not machine values."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from tools import system_tools as system


class SystemToolTests(unittest.TestCase):
    def test_system_info_omits_identifiers(self) -> None:
        result = system.get_system_info()
        self.assertTrue(result.success)
        self.assertEqual(set(result.data), {
            "os", "os_release", "os_version", "architecture", "python_version",
        })
        self.assertTrue(all(isinstance(value, str) for value in result.data.values()))

    def test_cpu_counts_and_unknown_count(self) -> None:
        with patch.object(psutil, "cpu_count", side_effect=[None, 8]) as count:
            result = system.get_cpu_info()
        self.assertEqual(result.data, {"physical_cores": None, "logical_cpus": 8})
        self.assertEqual(count.call_count, 2)

    def test_cpu_usage_is_a_real_interval_sample(self) -> None:
        with patch.object(psutil, "cpu_percent", return_value=12.5) as percent:
            result = system.get_cpu_usage()
        percent.assert_called_once_with(interval=0.1)
        self.assertEqual(result.data["percent"], 12.5)

    def test_memory_structure(self) -> None:
        memory = SimpleNamespace(total=1000, available=600, percent=40.0)
        with patch.object(psutil, "virtual_memory", return_value=memory):
            result = system.get_memory_info()
        self.assertEqual(result.data, {
            "total_bytes": 1000, "available_bytes": 600,
            "used_bytes": 400, "percent": 40.0,
        })

    def test_disk_structure(self) -> None:
        with TemporaryDirectory() as temporary:
            disk = SimpleNamespace(total=1000, used=250, free=750, percent=25.0)
            with patch.object(psutil, "disk_usage", return_value=disk) as usage:
                result = system.get_disk_info(Path(temporary))
            usage.assert_called_once_with(str(Path(temporary).resolve()))
        self.assertTrue(result.success)
        self.assertEqual(result.data["total_bytes"], 1000)
        self.assertEqual(result.data["used_bytes"] + result.data["free_bytes"], 1000)

    def test_disk_rejects_network_path_without_query(self) -> None:
        with patch.object(psutil, "disk_usage") as usage:
            result = system.get_disk_info(r"\\server\share")
        self.assertEqual(result.error_id, "INVALID_PATH")
        usage.assert_not_called()

    def test_process_list_is_bounded_and_requests_only_safe_attributes(self) -> None:
        processes = [SimpleNamespace(info={"pid": index, "name": "example"}) for index in range(5)]
        with patch.object(psutil, "process_iter", return_value=iter(processes)) as query:
            result = system.list_processes(limit=2)
        query.assert_called_once_with(attrs=["pid", "name"], ad_value=None)
        self.assertEqual(len(result.data["processes"]), 2)
        self.assertTrue(result.data["limit_reached"])
        self.assertTrue(all(set(row) == {"pid", "name"} for row in result.data["processes"]))

    def test_inaccessible_process_is_skipped(self) -> None:
        processes = [SimpleNamespace(info={"pid": 1, "name": None}), SimpleNamespace(info={"pid": 2, "name": "ok"})]
        with patch.object(psutil, "process_iter", return_value=iter(processes)):
            result = system.list_processes()
        self.assertEqual(result.data["skipped"], 1)
        self.assertEqual(len(result.data["processes"]), 1)

    def test_process_query_failure_is_sanitized(self) -> None:
        with patch.object(psutil, "process_iter", side_effect=psutil.AccessDenied(123)):
            result = system.list_processes()
        self.assertEqual(result.error_id, "PROCESS_QUERY_FAILED")
        self.assertNotIn("123", result.message)

    def test_invalid_process_limits(self) -> None:
        with patch.object(psutil, "process_iter") as query:
            for limit in (0, -1, 501, True, "2", None):
                with self.subTest(limit=limit):
                    self.assertEqual(system.list_processes(limit).error_id, "INVALID_ARGUMENT")
        query.assert_not_called()

    def test_unexpected_error_is_sanitized(self) -> None:
        with patch.object(psutil, "virtual_memory", side_effect=RuntimeError("sensitive")):
            result = system.get_memory_info()
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertNotIn("sensitive", result.message)
