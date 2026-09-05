"""Tests for codestats. Run with: python -m unittest discover -s tests"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import codestats  # noqa: E402


def write(root, rel_path, text):
    path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


class LanguageDetectionTests(unittest.TestCase):
    def test_extensions(self):
        self.assertEqual(codestats.detect_language("main.py"), "Python")
        self.assertEqual(codestats.detect_language("app.tsx"), "TypeScript (TSX)")
        self.assertEqual(codestats.detect_language("style.scss"), "SCSS")
        self.assertEqual(codestats.detect_language("lib.rs"), "Rust")

    def test_extension_case_is_ignored(self):
        self.assertEqual(codestats.detect_language("MAIN.PY"), "Python")

    def test_special_filenames(self):
        self.assertEqual(codestats.detect_language("Dockerfile"), "Dockerfile")
        self.assertEqual(codestats.detect_language("Makefile"), "Makefile")
        self.assertEqual(codestats.detect_language("CMakeLists.txt"), "CMake")

    def test_unknown_extension(self):
        self.assertIsNone(codestats.detect_language("archive.qqq"))

    def test_cpp_family(self):
        for name in ("main.cpp", "app.cc", "old.cxx", "weird.c++",
                     "matrix.ipp", "traits.tpp"):
            self.assertEqual(codestats.detect_language(name), "C++", name)
        for name in ("widget.hpp", "widget.hh", "widget.hxx", "widget.h++",
                     "impl.inl"):
            self.assertEqual(codestats.detect_language(name), "C++ Header", name)
        for name in ("engine.ixx", "engine.cppm"):
            self.assertEqual(codestats.detect_language(name), "C++ Module", name)
        self.assertEqual(codestats.detect_language("kernel.cu"), "CUDA")

    def test_arduino_sketches_count_as_cpp(self):
        self.assertEqual(codestats.detect_language("sketch.ino"), "C++ (Arduino)")
        self.assertEqual(codestats.detect_language("old.pde"), "C++ (Arduino)")
        _, code, comments, _ = codestats.count_lines(
            "// setup\nvoid setup() {}\n", "C++ (Arduino)")
        self.assertEqual((code, comments), (1, 1))

    def test_cpp_toolchain_files(self):
        self.assertEqual(codestats.detect_language("App.vcxproj"), "MSBuild")
        self.assertEqual(codestats.detect_language("App.sln"), "Visual Studio Solution")
        self.assertEqual(codestats.detect_language("App.pro"), "QMake")
        self.assertEqual(codestats.detect_language("App.rc"), "Windows Resource")
        self.assertEqual(codestats.detect_language("meson.build"), "Meson")
        self.assertEqual(codestats.detect_language("Makefile.am"), "Automake")
        self.assertEqual(codestats.detect_language("shader.frag"), "GLSL")
        self.assertEqual(codestats.detect_language("light.hlsl"), "HLSL")

    def test_template_suffix_falls_back_to_inner_extension(self):
        self.assertEqual(codestats.detect_language("config.h.in"), "C Header")
        self.assertEqual(codestats.detect_language("version.hpp.in"), "C++ Header")
        self.assertEqual(codestats.detect_language("Makefile.in"), "Makefile")
        self.assertEqual(codestats.detect_language("mikrotik.env.example"), "Config")
        self.assertEqual(codestats.detect_language("settings.json.sample"), "JSON")

    def test_dot_m_resolves_by_content(self):
        with tempfile.TemporaryDirectory() as root:
            objc = write(root, "bridge.m", "#import <Foundation/Foundation.h>\n@interface A\n@end\n")
            self.assertEqual(codestats.detect_language("bridge.m", objc), "Objective-C")

            matlab = write(root, "solve.m", "function y = solve(x)\ny = x + 1;\nend\n")
            self.assertEqual(codestats.detect_language("solve.m", matlab), "MATLAB")

    def test_dot_m_defaults_to_objective_c_without_hints(self):
        self.assertEqual(codestats.detect_language("empty.m"), "Objective-C")

    def test_cpp_comment_counting(self):
        source = "// note\n/* block\n   more */\nint main() { return 0; }\n"
        _, code, comments, _ = codestats.count_lines(source, "C++")
        self.assertEqual((code, comments), (1, 3))
        _, _, comments, _ = codestats.count_lines("<!-- x -->\n<Project/>\n", "MSBuild")
        self.assertEqual(comments, 1)

    def test_shebang_for_extensionless_files(self):
        with tempfile.TemporaryDirectory() as root:
            script = write(root, "runme", "#!/usr/bin/env python3\nprint(1)\n")
            self.assertEqual(codestats.detect_language("runme", script), "Python")

            shell = write(root, "deploy", "#!/bin/bash\necho hi\n")
            self.assertEqual(codestats.detect_language("deploy", shell), "Shell")

            plain = write(root, "notes", "just text\n")
            self.assertIsNone(codestats.detect_language("notes", plain))


class LineCountingTests(unittest.TestCase):
    def test_python_line_comments_and_docstrings(self):
        source = (
            '"""Module docstring.\n'
            'Second line.\n'
            '"""\n'
            "\n"
            "# a comment\n"
            "value = 1  # trailing comment counts as code\n"
        )
        total, code, comments, blanks = codestats.count_lines(source, "Python")
        self.assertEqual(total, 6)
        self.assertEqual(comments, 4)
        self.assertEqual(code, 1)
        self.assertEqual(blanks, 1)

    def test_c_style_block_comment(self):
        source = "/*\n * header\n */\nint main(void) { return 0; }\n"
        total, code, comments, blanks = codestats.count_lines(source, "C")
        self.assertEqual((total, code, comments, blanks), (4, 1, 3, 0))

    def test_code_after_block_comment_ends(self):
        source = "/* note */ int x = 1;\n"
        _, code, comments, _ = codestats.count_lines(source, "C")
        self.assertEqual((code, comments), (1, 0))

    def test_blank_line_inside_block_comment_counts_as_blank(self):
        source = "/*\n\nstill inside\n*/\n"
        total, code, comments, blanks = codestats.count_lines(source, "C")
        self.assertEqual((total, code, comments, blanks), (4, 0, 3, 1))

    def test_html_comments(self):
        source = "<!-- hidden -->\n<p>text</p>\n"
        _, code, comments, _ = codestats.count_lines(source, "HTML")
        self.assertEqual((code, comments), (1, 1))

    def test_sql_and_lua_use_dash_comments(self):
        _, code, comments, _ = codestats.count_lines("-- note\nSELECT 1;\n", "SQL")
        self.assertEqual((code, comments), (1, 1))
        _, code, comments, _ = codestats.count_lines("-- note\nprint(1)\n", "Lua")
        self.assertEqual((code, comments), (1, 1))

    def test_language_without_known_comment_syntax(self):
        _, code, comments, _ = codestats.count_lines("a,b\n1,2\n", "CSV")
        self.assertEqual((code, comments), (2, 0))

    def test_empty_file(self):
        self.assertEqual(codestats.count_lines("", "Python"), (0, 0, 0, 0))

    def test_file_without_trailing_newline(self):
        total, code, _, _ = codestats.count_lines("x = 1", "Python")
        self.assertEqual((total, code), (1, 1))

    def test_crlf_line_endings(self):
        total, code, comments, blanks = codestats.count_lines("# c\r\nx = 1\r\n\r\n", "Python")
        self.assertEqual((total, code, comments, blanks), (3, 1, 1, 1))


class GitIgnoreTests(unittest.TestCase):
    def matcher(self, *patterns):
        rules = codestats.GitIgnore()
        for pattern in patterns:
            rules.add_pattern(pattern)
        return rules

    def test_simple_name(self):
        rules = self.matcher("secret.txt")
        self.assertTrue(rules.matches("secret.txt", is_dir=False))
        self.assertTrue(rules.matches("nested/secret.txt", is_dir=False))
        self.assertFalse(rules.matches("public.txt", is_dir=False))

    def test_glob(self):
        rules = self.matcher("*.log")
        self.assertTrue(rules.matches("debug.log", is_dir=False))
        self.assertTrue(rules.matches("logs/debug.log", is_dir=False))
        self.assertFalse(rules.matches("debug.txt", is_dir=False))

    def test_anchored_pattern(self):
        rules = self.matcher("/build")
        self.assertTrue(rules.matches("build", is_dir=True))
        self.assertFalse(rules.matches("app/build", is_dir=True))

    def test_directory_only_pattern(self):
        rules = self.matcher("cache/")
        self.assertTrue(rules.matches("cache", is_dir=True))
        self.assertTrue(rules.matches("cache/file.py", is_dir=False))
        self.assertFalse(rules.matches("cache", is_dir=False))

    def test_negation(self):
        rules = self.matcher("*.log", "!keep.log")
        self.assertTrue(rules.matches("debug.log", is_dir=False))
        self.assertFalse(rules.matches("keep.log", is_dir=False))

    def test_double_star(self):
        rules = self.matcher("docs/**/draft.md")
        self.assertTrue(rules.matches("docs/draft.md", is_dir=False))
        self.assertTrue(rules.matches("docs/a/b/draft.md", is_dir=False))
        self.assertFalse(rules.matches("other/draft.md", is_dir=False))

    def test_comments_and_blank_lines_are_skipped(self):
        rules = self.matcher("# a comment", "", "   ")
        self.assertEqual(rules.rules, [])

    def test_nested_gitignore_applies_to_its_subtree(self):
        rules = codestats.GitIgnore()
        rules.add_pattern("temp.py", base="pkg")
        self.assertTrue(rules.matches("pkg/temp.py", is_dir=False))
        self.assertFalse(rules.matches("temp.py", is_dir=False))


class ScanTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name
        write(self.root, "app.py", "# comment\nvalue = 1\n\n")
        write(self.root, "index.html", "<!-- c -->\n<p>hi</p>\n")
        write(self.root, "node_modules/dep/index.js", "module.exports = 1\n")
        write(self.root, "src/util.py", "def f():\n    return 2\n")
        write(self.root, "assets/logo.png", "not really a png\n")
        write(self.root, "notes.unknownext", "text\n")
        self.addCleanup(self._temp.cleanup)

    def filters(self, **overrides):
        defaults = dict(
            ignore_dirs=set(codestats.IGNORE_DIRS),
            ignore_files=set(codestats.IGNORE_FILES),
            ignore_exts=set(codestats.IGNORE_EXTS),
            exclude_globs=[],
            include_globs=[],
            include_hidden=False,
            max_bytes=None,
            gitignore=None,
        )
        defaults.update(overrides)
        return codestats.Filters(**defaults)

    def test_counts_by_language(self):
        result = codestats.scan(self.root, self.filters())
        self.assertEqual(set(result.languages), {"Python", "HTML"})
        self.assertEqual(result.languages["Python"].files, 2)
        self.assertEqual(result.total.files, 3)

    def test_dependency_directory_is_skipped(self):
        result = codestats.scan(self.root, self.filters())
        self.assertNotIn("JavaScript", result.languages)

    def test_binary_extension_is_skipped(self):
        result = codestats.scan(self.root, self.filters())
        paths = [entry.path for entry in result.files]
        self.assertNotIn("assets/logo.png", paths)

    def test_unrecognized_files_are_reported(self):
        result = codestats.scan(self.root, self.filters())
        self.assertEqual(result.skipped_unknown, 1)

    def test_exclude_glob(self):
        result = codestats.scan(self.root, self.filters(exclude_globs=["src/*"]))
        paths = [entry.path for entry in result.files]
        self.assertNotIn("src/util.py", paths)
        self.assertIn("app.py", paths)

    def test_only_glob(self):
        result = codestats.scan(self.root, self.filters(include_globs=["*.py"]))
        self.assertEqual(set(result.languages), {"Python"})

    def test_max_size(self):
        result = codestats.scan(self.root, self.filters(max_bytes=5))
        self.assertGreater(result.skipped_large, 0)

    def test_hidden_files_skipped_by_default(self):
        write(self.root, ".hidden.py", "x = 1\n")
        default = codestats.scan(self.root, self.filters())
        self.assertEqual(default.languages["Python"].files, 2)
        with_hidden = codestats.scan(self.root, self.filters(include_hidden=True))
        self.assertEqual(with_hidden.languages["Python"].files, 3)

    def test_gitignore_is_honoured(self):
        write(self.root, ".gitignore", "src/\n")
        rules = codestats.GitIgnore()
        result = codestats.scan(self.root, self.filters(gitignore=rules))
        paths = [entry.path for entry in result.files]
        self.assertNotIn("src/util.py", paths)

    def test_binary_content_is_skipped(self):
        with open(os.path.join(self.root, "blob.py"), "wb") as handle:
            handle.write(b"\x00\x01\x02binary")
        result = codestats.scan(self.root, self.filters())
        self.assertEqual(result.skipped_binary, 1)

    def test_unknown_files_are_recorded_with_paths(self):
        result = codestats.scan(self.root, self.filters())
        self.assertEqual(result.unknown_files, ["notes.unknownext"])
        self.assertEqual(result.unknown_by_extension(), [(".unknownext", 1)])

    def test_unknown_grouping_counts_extensionless_files(self):
        write(self.root, "CHANGELOG", "history\n")
        result = codestats.scan(self.root, self.filters())
        grouped = dict(result.unknown_by_extension())
        self.assertEqual(grouped["(no extension)"], 1)

    def test_skipped_directories_are_recorded_with_a_reason(self):
        result = codestats.scan(self.root, self.filters())
        self.assertIn(("node_modules", "ignore list"), result.skipped_dirs)

    def test_skipped_directories_grouped_by_reason(self):
        write(self.root, ".gitignore", "src/\n")
        write(self.root, ".hidden/thing.py", "x = 1\n")
        result = codestats.scan(self.root, self.filters(gitignore=codestats.GitIgnore()))
        grouped = dict(result.skipped_dirs_by_reason())
        self.assertIn("src", grouped[".gitignore"])
        self.assertIn(".hidden", grouped["hidden"])
        self.assertIn("node_modules", grouped["ignore list"])

    def test_excluded_directory_names_the_exclude_flag(self):
        result = codestats.scan(self.root, self.filters(exclude_globs=["src"]))
        grouped = dict(result.skipped_dirs_by_reason())
        self.assertIn("src", grouped["--exclude"])

    def test_unknown_binary_file_counts_as_binary_not_unrecognized(self):
        with open(os.path.join(self.root, "core.pak"), "wb") as handle:
            handle.write(b"RIFF\x00\x00\x01binary payload")
        result = codestats.scan(self.root, self.filters(ignore_exts=set()))
        self.assertNotIn("core.pak", result.unknown_files)
        self.assertGreaterEqual(result.skipped_binary, 1)

    def test_unknown_text_file_is_still_reported(self):
        write(self.root, "notes.qqq", "plain text\n")
        result = codestats.scan(self.root, self.filters())
        self.assertIn("notes.qqq", result.unknown_files)

    def test_totals_match_language_sums(self):
        result = codestats.scan(self.root, self.filters())
        self.assertEqual(
            result.total.lines,
            sum(stats.lines for stats in result.languages.values()),
        )


class FormattingTests(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(codestats.human_size(0), "0B")
        self.assertEqual(codestats.human_size(512), "512B")
        self.assertEqual(codestats.human_size(2048), "2.0KB")
        self.assertEqual(codestats.human_size(5 * 1024 * 1024), "5.0MB")

    def test_plural(self):
        self.assertEqual(codestats.plural(1, "file"), "file")
        self.assertEqual(codestats.plural(2, "file"), "files")

    def test_render_bar(self):
        self.assertEqual(codestats.render_bar(0.0, 4), "....")
        self.assertEqual(codestats.render_bar(1.0, 4), "####")
        self.assertEqual(codestats.render_bar(0.5, 4), "##..")

    def test_palette_can_be_disabled(self):
        self.assertEqual(codestats.Palette(False)("text", "bold"), "text")
        self.assertIn("text", codestats.Palette(True)("text", "bold"))

    def test_sort_languages(self):
        languages = {
            "Python": codestats.Stats(files=1, lines=10),
            "Go": codestats.Stats(files=3, lines=5),
        }
        by_lines = codestats.sort_languages(languages, "lines", reverse=True)
        self.assertEqual([name for name, _ in by_lines], ["Python", "Go"])
        by_files = codestats.sort_languages(languages, "files", reverse=True)
        self.assertEqual([name for name, _ in by_files], ["Go", "Python"])
        by_name = codestats.sort_languages(languages, "name", reverse=False)
        self.assertEqual([name for name, _ in by_name], ["Go", "Python"])

    def test_comment_ratio(self):
        stats = codestats.Stats(code=75, comments=25)
        self.assertAlmostEqual(codestats.comment_ratio(stats), 25.0)
        self.assertEqual(codestats.comment_ratio(codestats.Stats()), 0.0)


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = self._temp.name
        write(self.root, "app.py", "# comment\nvalue = 1\n")
        self.addCleanup(self._temp.cleanup)

    def run_cli(self, *argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = codestats.main([self.root, *argv])
        return code, buffer.getvalue()

    def test_table_output(self):
        code, output = self.run_cli("--color", "never")
        self.assertEqual(code, 0)
        self.assertIn("Python", output)
        self.assertIn("TOTAL", output)

    def test_json_output(self):
        code, output = self.run_cli("--json")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["total"]["files"], 1)
        self.assertEqual(payload["languages"]["Python"]["lines"], 2)

    def test_json_with_per_file(self):
        _, output = self.run_cli("--json", "--per-file")
        payload = json.loads(output)
        self.assertEqual(payload["files"][0]["path"], "app.py")

    def test_csv_output(self):
        code, output = self.run_cli("--csv")
        self.assertEqual(code, 0)
        rows = [line for line in output.strip().splitlines() if line]
        self.assertTrue(rows[0].startswith("language,files,lines"))
        self.assertTrue(rows[-1].startswith("TOTAL,"))

    def test_no_bar_drops_share_column(self):
        _, output = self.run_cli("--color", "never", "--no-bar")
        self.assertNotIn("Share", output)

    def test_show_unknown_lists_files_and_directories(self):
        write(self.root, "assets.pak", "binaryish\n")
        write(self.root, "node_modules/dep/index.js", "1\n")
        _, output = self.run_cli("--color", "never", "--show-unknown")
        self.assertIn("Unrecognized files (1)", output)
        self.assertIn("assets.pak", output)
        self.assertIn("Skipped directories", output)
        self.assertIn("node_modules", output)

    def test_footer_names_unknown_extensions(self):
        write(self.root, "assets.pak", "binaryish\n")
        _, output = self.run_cli("--color", "never")
        self.assertIn(".pak x1", output)
        self.assertIn("--show-unknown", output)

    def test_json_reports_unknown_extensions(self):
        write(self.root, "assets.pak", "binaryish\n")
        _, output = self.run_cli("--json")
        payload = json.loads(output)
        self.assertEqual(payload["skipped"]["unrecognized_extensions"], {".pak": 1})

    def test_missing_directory_returns_error_code(self):
        code = codestats.main([os.path.join(self.root, "does-not-exist")])
        self.assertEqual(code, 2)

    def test_json_and_csv_together_is_rejected(self):
        with self.assertRaises(SystemExit):
            codestats.main([self.root, "--json", "--csv"])

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as empty:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = codestats.main([empty])
            self.assertEqual(code, 0)
            self.assertIn("No recognized source files", buffer.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
