"""Filesystem tests touch only temporary trees; associated-app calls are mocked."""

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from security.validator import ValidationError, is_reparse_point, validate_local_path
from tools import file_tools as files


class FileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        boundary = patch("os.startfile", create=True)
        self.launch = boundary.start()
        self.addCleanup(boundary.stop)

    def make_file(self, name: str = "file.txt") -> Path:
        path = self.root / name
        path.write_text("preserve content", encoding="utf-8")
        return path

    def test_list_directory_and_types(self) -> None:
        self.make_file()
        (self.root / "folder").mkdir()
        result = files.list_directory(self.root)
        self.assertTrue(result.success)
        self.assertEqual(result.data["entries"], [
            {"name": "file.txt", "type": "file"}, {"name": "folder", "type": "directory"},
        ])
        self.launch.assert_not_called()

    def test_list_missing_path_or_file(self) -> None:
        self.assertEqual(files.list_directory(self.root / "missing").error_id, "PATH_NOT_FOUND")
        self.assertEqual(files.list_directory(self.make_file()).error_id, "NOT_A_DIRECTORY")

    def test_list_result_bound(self) -> None:
        for index in range(4):
            self.make_file(f"{index}.txt")
        result = files.list_directory(self.root, limit=2)
        self.assertEqual(len(result.data["entries"]), 2)
        self.assertTrue(result.data["limit_reached"])

    def test_invalid_limits(self) -> None:
        for limit in (0, -1, 501, True, "5"):
            self.assertEqual(files.list_directory(self.root, limit).error_id, "INVALID_ARGUMENT")
            self.assertEqual(files.find_files(self.root, limit=limit).error_id, "INVALID_ARGUMENT")

    def test_search_matches_filename_case_insensitively(self) -> None:
        self.make_file("UPPER.TXT")
        self.make_file("other.md")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "inner.txt").write_text("data", encoding="utf-8")
        result = files.find_files(self.root, "*.txt")
        self.assertEqual(set(result.data["files"]), {"UPPER.TXT", str(Path("nested") / "inner.txt")})
        self.assertFalse(result.data["limit_reached"])

    def test_search_result_limit(self) -> None:
        for index in range(4):
            self.make_file(f"{index}.txt")
        result = files.find_files(self.root, limit=2)
        self.assertEqual(len(result.data["files"]), 2)
        self.assertTrue(result.data["limit_reached"])

    def test_search_entry_budget_bounds_nonmatching_files(self) -> None:
        for index in range(6):
            self.make_file(f"{index}.txt")
        result = files.find_files(self.root, "*.pdf", max_entries=3)
        self.assertEqual(result.data["files"], [])
        self.assertEqual(result.data["scanned_entries"], 3)
        self.assertTrue(result.data["limit_reached"])

    def test_search_depth_limit(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "inner.txt").write_text("data", encoding="utf-8")
        result = files.find_files(self.root, max_depth=0)
        self.assertEqual(result.data["files"], [])
        self.assertTrue(result.data["depth_limited"])

    def test_search_invalid_arguments(self) -> None:
        for kwargs in ({"max_depth": -1}, {"max_depth": 11}, {"max_depth": True},
                       {"max_entries": 10001}, {"pattern": "../*"}, {"pattern": ""}):
            self.assertEqual(files.find_files(self.root, **kwargs).error_id, "INVALID_ARGUMENT")

    def test_search_missing_or_file_root(self) -> None:
        self.assertEqual(files.find_files(self.root / "missing").error_id, "PATH_NOT_FOUND")
        self.assertEqual(files.find_files(self.make_file()).error_id, "NOT_A_DIRECTORY")

    def test_search_inaccessible_child_is_skipped(self) -> None:
        nested = self.root / "locked"
        nested.mkdir()
        original = os.scandir

        def scan(path):
            if Path(path) == nested:
                raise PermissionError("sensitive")
            return original(path)

        with patch("tools.file_tools.os.scandir", side_effect=scan):
            result = files.find_files(self.root)
        self.assertTrue(result.success)
        self.assertEqual(result.data["skipped"], 1)

    def test_inaccessible_root_is_failure(self) -> None:
        with patch("tools.file_tools.os.scandir", side_effect=PermissionError("sensitive")):
            for operation in (files.list_directory, files.find_files):
                result = operation(self.root)
                self.assertEqual(result.error_id, "ACCESS_DENIED")
                self.assertNotIn("sensitive", result.message)

    def test_create_directory(self) -> None:
        destination = self.root / "new"
        self.assertTrue(files.create_directory(destination).success)
        self.assertTrue(destination.is_dir())

    def test_create_rejects_existing_file_and_directory(self) -> None:
        for destination in (self.root, self.make_file()):
            self.assertEqual(files.create_directory(destination).error_id, "DESTINATION_EXISTS")
        self.assertEqual((self.root / "file.txt").read_text(encoding="utf-8"), "preserve content")

    def test_create_requires_existing_parent(self) -> None:
        self.assertEqual(files.create_directory(self.root / "missing" / "new").error_id, "PATH_NOT_FOUND")
        self.assertFalse((self.root / "missing").exists())

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_rename_preserves_content(self) -> None:
        source = self.make_file()
        self.assertTrue(files.rename_path(source, "renamed.txt").success)
        self.assertFalse(source.exists())
        self.assertEqual((self.root / "renamed.txt").read_text(encoding="utf-8"), "preserve content")

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_move_to_exact_destination(self) -> None:
        source = self.make_file()
        folder = self.root / "destination"
        folder.mkdir()
        target = folder / "moved.txt"
        self.assertTrue(files.move_path(source, target).success)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve content")

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_directory_move_preserves_tree(self) -> None:
        source = self.root / "folder"
        source.mkdir()
        (source / "child.txt").write_text("child", encoding="utf-8")
        self.assertTrue(files.move_path(source, self.root / "moved").success)
        self.assertEqual((self.root / "moved" / "child.txt").read_text(encoding="utf-8"), "child")

    def test_rename_and_move_collision_preserve_both_files(self) -> None:
        source = self.make_file("source.txt")
        destination = self.make_file("destination.txt")
        for result in (files.rename_path(source, destination.name), files.move_path(source, destination)):
            self.assertEqual(result.error_id, "DESTINATION_EXISTS")
        self.assertTrue(source.exists())
        self.assertTrue(destination.exists())

    def test_missing_source_and_invalid_new_name(self) -> None:
        self.assertEqual(files.move_path(self.root / "missing", self.root / "target").error_id, "PATH_NOT_FOUND")
        self.assertEqual(files.rename_path(self.root / "missing", "name").error_id, "PATH_NOT_FOUND")
        source = self.make_file()
        for name in ("../evil", "..", "a/b", "C:\\evil", "NUL", "CON.txt", "CON .txt", "file:stream", "bad.", "bad "):
            self.assertEqual(files.rename_path(source, name).error_id, "INVALID_PATH")
        self.assertTrue(source.exists())

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_move_inside_itself_rejected(self) -> None:
        source = self.root / "folder"
        source.mkdir()
        self.assertEqual(files.move_path(source, source / "child").error_id, "INVALID_PATH")

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_collision_at_rename_boundary_preserves_source(self) -> None:
        source = self.make_file()
        target = self.root / "late.txt"
        original = os.rename

        def racing_rename(src, dst):
            target.write_text("other actor", encoding="utf-8")
            original(src, dst)

        with patch("tools.file_tools.os.rename", side_effect=racing_rename):
            result = files.move_path(source, target)
        self.assertEqual(result.error_id, "DESTINATION_EXISTS")
        self.assertTrue(source.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "other actor")

    @unittest.skipUnless(os.name == "nt", "Windows no-replacement rename semantics")
    def test_cross_volume_move_is_rejected(self) -> None:
        source = self.make_file()
        original = Path.stat

        def device(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == source and not kwargs:
                values = list(info)
                values[2] = info.st_dev + 1
                return os.stat_result(values)
            return info

        with patch.object(Path, "stat", device), patch("tools.file_tools.os.rename") as rename:
            result = files.move_path(source, self.root / "target")
        self.assertEqual(result.error_id, "CROSS_DEVICE_MOVE")
        rename.assert_not_called()

    def test_invalid_path_syntax_is_rejected(self) -> None:
        for value in ("", " ", "bad\x00path", "../outside", "https://example.com", r"\\server\share", r"\\?\C:\file", "C:relative", "file.txt:stream", "NUL", None):
            with self.subTest(value=value):
                self.assertEqual(files.list_directory(value).error_id, "INVALID_PATH")

    def test_relative_paths_resolve_against_project_root(self) -> None:
        self.make_file()
        with patch("security.validator.PROJECT_ROOT", self.root):
            self.assertTrue(files.list_directory(".").success)
            self.assertEqual(validate_local_path("file.txt"), self.root / "file.txt")

    def test_reparse_attribute_is_recognized_without_symlink_privileges(self) -> None:
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        self.assertTrue(is_reparse_point(info))

    def test_reparse_component_is_rejected_before_resolve(self) -> None:
        blocked = self.root / "junction"
        blocked.mkdir()
        original = Path.lstat

        def inspect(path):
            if path == blocked:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(path)

        with patch.object(Path, "lstat", inspect):
            for result in (files.list_directory(blocked), files.create_directory(blocked / "child"), files.move_path(blocked, self.root / "new")):
                self.assertEqual(result.error_id, "UNSAFE_PATH")

    def test_real_symlink_is_not_followed_when_supported(self) -> None:
        target = self.root / "target"
        target.mkdir()
        (target / "inside.txt").write_text("data", encoding="utf-8")
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation requires Windows developer mode or privileges")
        self.assertEqual(files.list_directory(link).error_id, "UNSAFE_PATH")
        self.assertEqual(files.create_directory(link / "new").error_id, "UNSAFE_PATH")
        result = files.find_files(self.root)
        self.assertEqual(result.data["files"], [str(Path("target") / "inside.txt")])
        self.assertGreaterEqual(result.data["skipped"], 1)

    def test_remote_drive_check_fails_closed(self) -> None:
        with patch("security.validator._require_local_drive", side_effect=ValidationError("UNSAFE_PATH")):
            self.assertEqual(files.list_directory(self.root).error_id, "UNSAFE_PATH")

    @unittest.skipUnless(os.name == "nt", "Windows associations")
    def test_open_directory_and_safe_document(self) -> None:
        document = self.make_file()
        self.assertTrue(files.open_path(self.root).success)
        self.assertTrue(files.open_path(document).success)
        self.launch.assert_called_with(str(document), "open")

    def test_open_rejects_executables_scripts_links_and_active_content(self) -> None:
        for suffix in (".exe", ".com", ".bat", ".cmd", ".ps1", ".py", ".lnk", ".url", ".html", ".svg", ".docm"):
            self.assertEqual(files.open_path(self.make_file("unsafe" + suffix)).error_id, "UNSUPPORTED_FILE_TYPE")
        self.launch.assert_not_called()

    def test_open_missing_or_url(self) -> None:
        self.assertEqual(files.open_path(self.root / "missing").error_id, "PATH_NOT_FOUND")
        self.assertEqual(files.open_path("https://example.com").error_id, "INVALID_PATH")
        self.launch.assert_not_called()
