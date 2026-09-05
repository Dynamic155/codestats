#!/usr/bin/env python3
"""
codestats - a single-file code statistics tool.

Drop codestats.py into a project and run it:

    python codestats.py

It walks the tree, groups files by language, and prints how many files,
lines, code lines, comment lines and blank lines each language accounts
for. Dependency folders, build output, lockfiles and binaries are skipped
by default, and .gitignore rules are honoured.

Stdlib only. No install step, no third-party packages.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

__version__ = "1.2.0"


# ==========================================================================
# Configuration
# ==========================================================================

# Directory names skipped anywhere in the tree.
IGNORE_DIRS = {
    # Version control
    ".git", ".hg", ".svn", ".bzr",
    # JavaScript / TypeScript
    "node_modules", "bower_components", ".next", ".nuxt", ".svelte-kit",
    ".parcel-cache", ".turbo", ".angular", ".astro", ".output",
    # Python
    "__pycache__", ".venv", "venv", "env", ".tox", ".nox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "site-packages", ".eggs", ".hypothesis",
    # Build and dist output
    "dist", "build", "out", "target", "bin", "obj", ".gradle", ".dart_tool",
    "cmake-build-debug", "cmake-build-release", "DerivedData", "_build",
    # Package managers and infrastructure
    ".terraform", "vendor", "Pods", ".bundle", ".pub-cache",
    # Caches, editors, coverage
    ".cache", ".idea", ".vscode", ".vs", ".fleet", "coverage", "htmlcov",
    ".nyc_output", ".serverless", ".sass-cache", "__snapshots__",
}

# Exact file names always skipped.
IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "npm-shrinkwrap.json", "Gemfile.lock", "poetry.lock", "Pipfile.lock",
    "Cargo.lock", "composer.lock", "go.sum", "mix.lock", "pubspec.lock",
    "packages.lock.json", "Podfile.lock", "flake.lock",
}

# File name suffixes always skipped: binaries, media, minified output.
IGNORE_EXTS = {
    ".min.js", ".min.css", ".min.mjs", ".map", ".bundle.js",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".icns", ".webp",
    ".tif", ".tiff", ".psd", ".ai", ".eps",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wav", ".flac",
    ".ogg", ".m4a", ".aac",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib", ".obj", ".class",
    ".pyc", ".pyo", ".pyd", ".wasm", ".bin", ".dat",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".lock",
    ".pem", ".key", ".crt", ".p12", ".keystore", ".jks",
}

# Extension -> language name.
LANGUAGE_MAP = {
    # Scripting
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".rb": "Ruby", ".rake": "Ruby", ".gemspec": "Ruby",
    ".php": "PHP", ".phtml": "PHP",
    ".pl": "Perl", ".pm": "Perl",
    ".lua": "Lua",
    ".tcl": "Tcl",
    ".r": "R", ".rmd": "R Markdown",
    ".jl": "Julia",
    ".groovy": "Groovy", ".gradle": "Gradle",
    ".m": "Objective-C",  # or MATLAB; decided by content, see AMBIGUOUS_EXTS
    # Web
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".tsx": "TypeScript (TSX)",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".html": "HTML", ".htm": "HTML", ".xhtml": "HTML",
    ".ejs": "EJS", ".hbs": "Handlebars", ".pug": "Pug", ".jade": "Pug",
    ".twig": "Twig", ".liquid": "Liquid", ".mustache": "Mustache",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".styl": "Stylus",
    # Systems
    ".c": "C", ".h": "C Header",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".c++": "C++",
    ".ipp": "C++", ".tpp": "C++", ".txx": "C++",
    ".ixx": "C++ Module", ".cppm": "C++ Module", ".mpp": "C++ Module",
    ".hpp": "C++ Header", ".hh": "C++ Header", ".hxx": "C++ Header",
    ".h++": "C++ Header", ".inl": "C++ Header",
    ".cu": "CUDA", ".cuh": "CUDA Header",
    ".ino": "Arduino", ".pde": "Arduino",
    ".cs": "C#", ".csx": "C#",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".go": "Go",
    ".rs": "Rust",
    ".swift": "Swift",
    ".mm": "Objective-C++",
    ".zig": "Zig",
    ".d": "D",
    ".nim": "Nim",
    ".cr": "Crystal",
    ".dart": "Dart",
    ".vb": "Visual Basic",
    ".pas": "Pascal",
    ".f90": "Fortran", ".f95": "Fortran", ".f": "Fortran",
    ".asm": "Assembly", ".s": "Assembly",
    # Functional
    ".hs": "Haskell", ".lhs": "Haskell",
    ".elm": "Elm",
    ".ml": "OCaml", ".mli": "OCaml",
    ".fs": "F#", ".fsi": "F#", ".fsx": "F#",
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hrl": "Erlang",
    ".clj": "Clojure", ".cljs": "ClojureScript", ".cljc": "Clojure",
    ".lisp": "Lisp", ".el": "Emacs Lisp", ".scm": "Scheme",
    ".rkt": "Racket",
    # Shell and config
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ksh": "Shell",
    ".fish": "Fish",
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch",
    ".json": "JSON", ".jsonc": "JSON", ".json5": "JSON",
    ".yml": "YAML", ".yaml": "YAML",
    ".toml": "TOML",
    ".xml": "XML", ".xsd": "XML", ".xsl": "XML", ".plist": "XML",
    ".ini": "INI", ".cfg": "INI", ".conf": "Config", ".properties": "Config",
    ".env": "Config",
    ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL",
    ".proto": "Protobuf",
    ".graphql": "GraphQL", ".gql": "GraphQL",
    ".sql": "SQL", ".psql": "SQL",
    ".prisma": "Prisma",
    ".nix": "Nix",
    ".cmake": "CMake",
    ".mk": "Makefile", ".mak": "Makefile", ".make": "Makefile",
    # C and C++ toolchain files
    ".vcxproj": "MSBuild", ".vcproj": "MSBuild", ".csproj": "MSBuild",
    ".props": "MSBuild", ".targets": "MSBuild", ".filters": "MSBuild",
    ".sln": "Visual Studio Solution",
    ".pro": "QMake", ".pri": "QMake",
    ".ui": "Qt UI", ".qrc": "Qt Resource", ".natvis": "XML",
    ".am": "Automake", ".ac": "Autoconf", ".m4": "M4",
    ".ninja": "Ninja", ".bzl": "Starlark",
    ".rc": "Windows Resource", ".def": "Module Definition", ".idl": "IDL",
    ".ld": "Linker Script", ".lds": "Linker Script",
    # Shaders
    ".hlsl": "HLSL", ".fx": "HLSL", ".compute": "HLSL",
    ".glsl": "GLSL", ".vert": "GLSL", ".frag": "GLSL", ".geom": "GLSL",
    ".comp": "GLSL", ".tesc": "GLSL", ".tese": "GLSL",
    ".metal": "Metal", ".wgsl": "WGSL", ".shader": "ShaderLab",
    ".patch": "Diff", ".diff": "Diff",
    # Docs and data
    ".md": "Markdown", ".markdown": "Markdown", ".mdx": "MDX",
    ".rst": "reStructuredText",
    ".tex": "LaTeX", ".bib": "BibTeX",
    ".adoc": "AsciiDoc",
    ".txt": "Text",
    ".csv": "CSV", ".tsv": "CSV",
    ".vim": "Vimscript",
    ".sol": "Solidity",
    ".gd": "GDScript",
    ".ahk": "AutoHotkey",
}

# Files with no extension, or with a name more telling than the extension.
SPECIAL_FILENAMES = {
    "Dockerfile": "Dockerfile", "dockerfile": "Dockerfile",
    "Containerfile": "Dockerfile",
    "Makefile": "Makefile", "makefile": "Makefile", "GNUmakefile": "Makefile",
    "Rakefile": "Ruby", "Gemfile": "Ruby", "Vagrantfile": "Ruby",
    "Podfile": "Ruby", "Brewfile": "Ruby",
    "CMakeLists.txt": "CMake", "CMakePresets.json": "JSON",
    "meson.build": "Meson", "meson_options.txt": "Meson",
    "SConstruct": "Python", "SConscript": "Python",
    "Kbuild": "Makefile", "Makefile.am": "Automake",
    "configure.ac": "Autoconf", "configure.in": "Autoconf",
    "Jenkinsfile": "Groovy",
    "BUILD": "Bazel", "WORKSPACE": "Bazel", "BUILD.bazel": "Bazel",
    ".clang-format": "YAML", ".clang-tidy": "YAML", ".gitmodules": "Config",
    "compile_flags.txt": "Config", "vcpkg.json": "JSON",
    "requirements.txt": "Config", "constraints.txt": "Config",
    ".gitignore": "Config", ".gitattributes": "Config",
    ".dockerignore": "Config", ".editorconfig": "Config",
    ".npmrc": "Config", ".nvmrc": "Config", ".prettierrc": "Config",
    ".eslintrc": "Config", ".babelrc": "Config",
    "LICENSE": "Text", "LICENCE": "Text", "COPYING": "Text", "NOTICE": "Text",
}

# Interpreter named in a shebang -> language, for extensionless scripts.
SHEBANG_MAP = {
    "python": "Python", "python2": "Python", "python3": "Python",
    "sh": "Shell", "bash": "Shell", "zsh": "Shell", "ksh": "Shell",
    "fish": "Fish",
    "node": "JavaScript", "deno": "TypeScript", "bun": "TypeScript",
    "ruby": "Ruby", "perl": "Perl", "php": "PHP", "lua": "Lua",
    "Rscript": "R", "julia": "Julia", "pwsh": "PowerShell",
}

# Language -> (line comment markers, block comment marker pairs).
C_STYLE = (("//",), (("/*", "*/"),))
HASH_STYLE = (("#",), ())
HTML_STYLE = ((), (("<!--", "-->"),))

COMMENT_SYNTAX = {
    "Python": (("#",), (('"""', '"""'), ("'''", "'''"))),
    "Ruby": (("#",), (("=begin", "=end"),)),
    "Shell": HASH_STYLE, "Fish": HASH_STYLE,
    "PowerShell": (("#",), (("<#", "#>"),)),
    "Perl": HASH_STYLE, "R": HASH_STYLE, "R Markdown": HASH_STYLE,
    "YAML": HASH_STYLE, "TOML": HASH_STYLE, "INI": (("#", ";"), ()),
    "Config": (("#", ";"), ()), "Dockerfile": HASH_STYLE,
    "Makefile": HASH_STYLE, "CMake": HASH_STYLE, "Gradle": C_STYLE,
    "Terraform": (("#", "//"), (("/*", "*/"),)),
    "HCL": (("#", "//"), (("/*", "*/"),)),
    "Nix": HASH_STYLE, "Elixir": HASH_STYLE, "Crystal": HASH_STYLE,
    "Julia": (("#",), (("#=", "=#"),)),
    "Tcl": HASH_STYLE, "GDScript": HASH_STYLE, "Bazel": HASH_STYLE,
    "Prisma": HASH_STYLE, "Batch": (("REM", "rem", "::"), ()),
    "JavaScript": C_STYLE, "JavaScript (JSX)": C_STYLE,
    "TypeScript": C_STYLE, "TypeScript (TSX)": C_STYLE,
    "C": C_STYLE, "C Header": C_STYLE, "C++": C_STYLE, "C++ Header": C_STYLE,
    "C#": C_STYLE, "Java": C_STYLE, "Kotlin": C_STYLE, "Scala": C_STYLE,
    "Go": C_STYLE, "Rust": C_STYLE, "Swift": C_STYLE, "Dart": C_STYLE,
    "Objective-C": C_STYLE, "Objective-C++": C_STYLE, "Zig": (("//",), ()),
    "C++ Module": C_STYLE, "CUDA": C_STYLE, "CUDA Header": C_STYLE,
    "Arduino": C_STYLE, "Windows Resource": C_STYLE, "IDL": C_STYLE,
    "HLSL": C_STYLE, "GLSL": C_STYLE, "Metal": C_STYLE, "WGSL": C_STYLE,
    "ShaderLab": C_STYLE, "Linker Script": ((), (("/*", "*/"),)),
    "Module Definition": ((";",), ()),
    "MSBuild": HTML_STYLE, "Qt UI": HTML_STYLE, "Qt Resource": HTML_STYLE,
    "QMake": HASH_STYLE, "Automake": HASH_STYLE, "Ninja": HASH_STYLE,
    "Meson": HASH_STYLE, "Starlark": HASH_STYLE,
    "Autoconf": (("dnl", "#"), ()), "M4": (("dnl", "#"), ()),
    "D": C_STYLE, "Nim": HASH_STYLE, "Solidity": C_STYLE,
    "PHP": (("//", "#"), (("/*", "*/"),)),
    "SQL": (("--",), (("/*", "*/"),)),
    "Lua": (("--",), (("--[[", "]]"),)),
    "Haskell": (("--",), (("{-", "-}"),)),
    "Elm": (("--",), (("{-", "-}"),)),
    "OCaml": ((), (("(*", "*)"),)),
    "F#": (("//",), (("(*", "*)"),)),
    "Pascal": (("//",), (("{", "}"), ("(*", "*)"))),
    "Erlang": (("%",), ()), "LaTeX": (("%",), ()), "BibTeX": (("%",), ()),
    "MATLAB": (("%",), (("%{", "%}"),)),
    "Clojure": ((";",), ()), "ClojureScript": ((";",), ()),
    "Lisp": ((";",), ()), "Emacs Lisp": ((";",), ()),
    "Scheme": ((";",), ()), "Racket": ((";",), ()),
    "Assembly": ((";", "#"), ()),
    "Visual Basic": (("'", "REM"), ()),
    "Fortran": (("!",), ()),
    "Vimscript": (('"',), ()),
    "AutoHotkey": ((";",), (("/*", "*/"),)),
    "CSS": ((), (("/*", "*/"),)),
    "SCSS": C_STYLE, "Sass": C_STYLE, "Less": C_STYLE, "Stylus": C_STYLE,
    "HTML": HTML_STYLE, "XML": HTML_STYLE, "Markdown": HTML_STYLE,
    "MDX": HTML_STYLE,
    "Vue": ((), (("<!--", "-->"), ("/*", "*/"))),
    "Svelte": ((), (("<!--", "-->"), ("/*", "*/"))),
    "Astro": ((), (("<!--", "-->"), ("/*", "*/"))),
    "EJS": ((), (("<%#", "%>"),)),
    "Handlebars": ((), (("{{!--", "--}}"), ("{{!", "}}"))),
    "Twig": ((), (("{#", "#}"),)),
    "Liquid": ((), (("{% comment %}", "{% endcomment %}"),)),
    "Mustache": ((), (("{{!", "}}"),)),
    "Pug": (("//-", "//"), ()),
    "GraphQL": HASH_STYLE, "Protobuf": C_STYLE, "Groovy": C_STYLE,
    "reStructuredText": ((".. ",), ()),
    "AsciiDoc": (("//",), (("////", "////"),)),
}

NO_COMMENT_SYNTAX = ((), ())

# Bar characters for the share column.
BAR_FULL = "#"
BAR_EMPTY = "."


# ==========================================================================
# Terminal colors
# ==========================================================================

class Palette:
    """ANSI escape codes, blanked out when color is disabled."""

    CODES = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
        "bright_black": "\033[90m",
        "bright_green": "\033[92m",
        "bright_yellow": "\033[93m",
        "bright_blue": "\033[94m",
        "bright_cyan": "\033[96m",
    }

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        prefix = "".join(self.CODES.get(s, "") for s in styles)
        return f"{prefix}{text}{self.CODES['reset']}"


def should_colorize(mode: str) -> bool:
    """Decide whether to emit ANSI codes, honouring NO_COLOR and TTY state."""
    if mode == "never":
        return False
    if mode == "always":
        enable_windows_ansi()
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        return enable_windows_ansi()
    return True


def enable_windows_ansi() -> bool:
    """Turn on virtual terminal processing so ANSI codes work in cmd.exe."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


# ==========================================================================
# Ignore rules
# ==========================================================================

class GitIgnore:
    """A small .gitignore matcher.

    Supports the parts of the format that matter for counting code: glob
    patterns, negation with !, anchoring with a leading slash, directory-only
    rules with a trailing slash, and ** segments. Rules from a nested
    .gitignore apply to that directory and below.
    """

    def __init__(self) -> None:
        # (base_dir_relative, compiled_regex, is_negation, dir_only)
        self.rules: list[tuple[str, re.Pattern[str], bool, bool]] = []

    def add_file(self, path: str, base: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                lines = handle.readlines()
        except OSError:
            return
        for line in lines:
            self.add_pattern(line, base)

    def add_pattern(self, raw: str, base: str = "") -> None:
        line = raw.rstrip("\n").rstrip()
        if not line or line.startswith("#"):
            return
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            return
        anchored = line.startswith("/") or "/" in line.rstrip("/")
        line = line.lstrip("/")
        self.rules.append((base, self._compile(line, anchored), negate, dir_only))

    @staticmethod
    def _compile(pattern: str, anchored: bool) -> re.Pattern[str]:
        parts: list[str] = []
        index = 0
        while index < len(pattern):
            char = pattern[index]
            if pattern.startswith("**/", index):
                parts.append("(?:.*/)?")
                index += 3
            elif pattern.startswith("**", index):
                parts.append(".*")
                index += 2
            elif char == "*":
                parts.append("[^/]*")
                index += 1
            elif char == "?":
                parts.append("[^/]")
                index += 1
            elif char == "[":
                close = pattern.find("]", index)
                if close == -1:
                    parts.append(re.escape(char))
                    index += 1
                else:
                    body = pattern[index + 1:close].replace("\\", "\\\\")
                    parts.append(f"[{body}]")
                    index = close + 1
            else:
                parts.append(re.escape(char))
                index += 1
        body = "".join(parts)
        prefix = "" if anchored else "(?:.*/)?"
        return re.compile(f"^{prefix}{body}(?:/.*)?$")

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        rel_path = rel_path.replace(os.sep, "/")
        ignored = False
        for base, regex, negate, dir_only in self.rules:
            if base and not rel_path.startswith(f"{base}/"):
                continue
            target = rel_path[len(base) + 1:] if base else rel_path
            if dir_only and not is_dir and "/" not in target:
                continue
            if regex.match(target):
                ignored = not negate
        return ignored


@dataclass
class Filters:
    """Everything that decides whether a path is counted."""

    ignore_dirs: set[str]
    ignore_files: set[str]
    ignore_exts: set[str]
    exclude_globs: list[str]
    include_globs: list[str]
    include_hidden: bool
    max_bytes: int | None
    gitignore: GitIgnore | None

    def skip_dir(self, name: str, rel_path: str) -> bool:
        if name in self.ignore_dirs:
            return True
        if not self.include_hidden and name.startswith(".") and name not in KEEP_HIDDEN:
            return True
        if any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(name, g) for g in self.exclude_globs):
            return True
        if self.gitignore and self.gitignore.matches(rel_path, is_dir=True):
            return True
        return False

    def skip_file(self, name: str, rel_path: str) -> bool:
        if name in self.ignore_files:
            return True
        if not self.include_hidden and name.startswith(".") and name not in SPECIAL_FILENAMES:
            return True
        lowered = name.lower()
        if any(lowered.endswith(ext) for ext in self.ignore_exts):
            return True
        if any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(name, g) for g in self.exclude_globs):
            return True
        if self.include_globs and not any(
            fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(name, g) for g in self.include_globs
        ):
            return True
        if self.gitignore and self.gitignore.matches(rel_path, is_dir=False):
            return True
        return False


# Hidden directories worth keeping, since they usually hold real config.
KEEP_HIDDEN = {".github", ".circleci", ".gitlab", ".husky", ".config"}


# ==========================================================================
# Counting
# ==========================================================================

@dataclass
class Stats:
    files: int = 0
    lines: int = 0
    code: int = 0
    comments: int = 0
    blanks: int = 0
    chars: int = 0
    size: int = 0

    def add(self, other: "Stats") -> None:
        self.files += other.files
        self.lines += other.lines
        self.code += other.code
        self.comments += other.comments
        self.blanks += other.blanks
        self.chars += other.chars
        self.size += other.size


@dataclass
class FileEntry:
    path: str
    language: str
    stats: Stats


@dataclass
class ScanResult:
    root: str
    languages: dict[str, Stats]
    files: list[FileEntry]
    total: Stats
    skipped_unknown: int = 0
    skipped_binary: int = 0
    skipped_large: int = 0
    duration: float = 0.0
    unknown_files: list[str] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)

    def unknown_by_extension(self) -> list[tuple[str, int]]:
        """Unrecognized files grouped by extension, most common first."""
        counts: dict[str, int] = defaultdict(int)
        for path in self.unknown_files:
            ext = os.path.splitext(path)[1].lower()
            counts[ext or "(no extension)"] += 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


# Suffixes that wrap another file name, e.g. config.h.in or main.cpp.template.
TEMPLATE_EXTS = {".in", ".tmpl", ".template", ".orig", ".bak"}

# Extensions two languages share, resolved by looking at the file itself.
AMBIGUOUS_EXTS = {".m"}

OBJC_HINT = re.compile(r"^\s*(#import|#include|@interface|@implementation|@property|@end)", re.M)
MATLAB_HINT = re.compile(r"^\s*(function\s|classdef\s|%%|end\s*$)", re.M)


def detect_language(filename: str, path: str | None = None) -> str | None:
    """Work out the language from the file name, then from a shebang."""
    if filename in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[filename]

    stem, ext = os.path.splitext(filename)
    lowered = ext.lower()

    # config.h.in is a C header, Makefile.in is a Makefile.
    if lowered in TEMPLATE_EXTS and stem:
        return detect_language(stem, path)

    if lowered in AMBIGUOUS_EXTS and path:
        resolved = resolve_ambiguous(lowered, path)
        if resolved:
            return resolved

    if ext:
        return LANGUAGE_MAP.get(lowered)
    if path:
        return language_from_shebang(path)
    return None


def resolve_ambiguous(ext: str, path: str) -> str | None:
    """Tell Objective-C and MATLAB apart by peeking at the file."""
    if ext != ".m":
        return None
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096).decode("utf-8", errors="ignore")
    except OSError:
        return None
    if OBJC_HINT.search(head):
        return "Objective-C"
    if MATLAB_HINT.search(head):
        return "MATLAB"
    return None


def language_from_shebang(path: str) -> str | None:
    try:
        with open(path, "rb") as handle:
            first = handle.readline(200)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    try:
        line = first.decode("utf-8", errors="ignore").strip()
    except ValueError:
        return None
    tokens = line[2:].replace("\\", "/").split()
    for token in tokens:
        name = token.rsplit("/", 1)[-1]
        if name in ("env", "-S"):
            continue
        if "=" in name:
            continue
        base = re.sub(r"[0-9.]+$", "", name) or name
        return SHEBANG_MAP.get(name) or SHEBANG_MAP.get(base)
    return None


def comment_syntax(language: str):
    return COMMENT_SYNTAX.get(language, NO_COMMENT_SYNTAX)


def count_lines(text: str, language: str) -> tuple[int, int, int, int]:
    """Return (total, code, comments, blanks) for one file's text.

    Comment detection is a line-level heuristic: a line counts as a comment
    when it starts with a comment marker or sits inside a block comment.
    Trailing comments on a line of code count as code, which is what most
    line counters do.
    """
    line_markers, block_pairs = comment_syntax(language)
    lines = text.splitlines()
    total = len(lines)
    code = comments = blanks = 0
    closing: str | None = None

    for raw in lines:
        line = raw.strip()

        if not line:
            blanks += 1
            continue

        if closing is not None:
            end = line.find(closing)
            if end == -1:
                comments += 1
                continue
            tail = line[end + len(closing):].strip()
            closing = None
            if tail and not _starts_comment(tail, line_markers):
                code += 1
            else:
                comments += 1
            continue

        if _starts_comment(line, line_markers):
            comments += 1
            continue

        pair = _opening_pair(line, block_pairs)
        if pair is None:
            code += 1
            continue

        opener, closer = pair
        rest = line[len(opener):]
        end = rest.find(closer)
        if end == -1:
            closing = closer
            comments += 1
            continue
        tail = rest[end + len(closer):].strip()
        if tail and not _starts_comment(tail, line_markers):
            code += 1
        else:
            comments += 1

    return total, code, comments, blanks


def _starts_comment(line: str, markers: tuple[str, ...]) -> bool:
    return any(line.startswith(marker) for marker in markers)


def _opening_pair(line: str, pairs: tuple[tuple[str, str], ...]):
    for opener, closer in pairs:
        if line.startswith(opener):
            return opener, closer
    return None


def read_text(path: str) -> tuple[str, int] | None:
    """Read a file as UTF-8 text. Returns None for binary or unreadable files."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(encoding), len(raw)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def scan(root: str, filters: Filters, follow_links: bool = False) -> ScanResult:
    started = time.perf_counter()
    languages: dict[str, Stats] = defaultdict(Stats)
    entries: list[FileEntry] = []
    total = Stats()
    skipped_unknown = skipped_binary = skipped_large = 0
    unknown_files: list[str] = []
    skipped_dirs: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_links):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")

        if filters.gitignore is not None and ".gitignore" in filenames:
            filters.gitignore.add_file(os.path.join(dirpath, ".gitignore"), rel_dir)

        kept: list[str] = []
        for name in sorted(dirnames):
            rel_sub = f"{rel_dir}/{name}" if rel_dir else name
            if filters.skip_dir(name, rel_sub):
                skipped_dirs.append(rel_sub)
            else:
                kept.append(name)
        dirnames[:] = kept

        for filename in sorted(filenames):
            rel_path = f"{rel_dir}/{filename}" if rel_dir else filename
            if filters.skip_file(filename, rel_path):
                continue

            full_path = os.path.join(dirpath, filename)
            language = detect_language(filename, full_path)
            if language is None:
                skipped_unknown += 1
                unknown_files.append(rel_path)
                continue

            if filters.max_bytes is not None:
                try:
                    if os.path.getsize(full_path) > filters.max_bytes:
                        skipped_large += 1
                        continue
                except OSError:
                    continue

            payload = read_text(full_path)
            if payload is None:
                skipped_binary += 1
                continue

            text, byte_len = payload
            lines, code, comments, blanks = count_lines(text, language)
            stats = Stats(
                files=1, lines=lines, code=code, comments=comments,
                blanks=blanks, chars=len(text), size=byte_len,
            )
            languages[language].add(stats)
            total.add(stats)
            entries.append(FileEntry(rel_path, language, stats))

    return ScanResult(
        root=root,
        languages=dict(languages),
        files=entries,
        total=total,
        skipped_unknown=skipped_unknown,
        unknown_files=unknown_files,
        skipped_dirs=skipped_dirs,
        skipped_binary=skipped_binary,
        skipped_large=skipped_large,
        duration=time.perf_counter() - started,
    )


# ==========================================================================
# Output
# ==========================================================================

SORT_KEYS = {
    "lines": lambda item: item[1].lines,
    "code": lambda item: item[1].code,
    "comments": lambda item: item[1].comments,
    "blanks": lambda item: item[1].blanks,
    "files": lambda item: item[1].files,
    "size": lambda item: item[1].size,
    "name": lambda item: item[0].lower(),
}


def plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def human_size(num: int) -> str:
    if num < 1024:
        return f"{num}B"
    value = float(num)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}"
    return f"{value:.1f}GB"


def sort_languages(languages: dict[str, Stats], key: str, reverse: bool) -> list[tuple[str, Stats]]:
    keyfunc = SORT_KEYS.get(key, SORT_KEYS["lines"])
    items = sorted(languages.items(), key=keyfunc, reverse=reverse)
    return items


def render_bar(fraction: float, width: int) -> str:
    filled = int(round(fraction * width))
    filled = max(0, min(width, filled))
    return BAR_FULL * filled + BAR_EMPTY * (width - filled)


def print_table(result: ScanResult, args: argparse.Namespace, paint: Palette) -> None:
    items = sort_languages(result.languages, args.sort, not args.ascending)
    shown = items[: args.top] if args.top else items

    headers = ["Language", "Files", "Lines", "Code", "Comment", "Blank", "Size"]
    if not args.no_bar:
        headers.append("Share")

    total = result.total
    rows: list[list[str]] = []
    for language, stats in shown:
        row = [
            language,
            f"{stats.files:,}",
            f"{stats.lines:,}",
            f"{stats.code:,}",
            f"{stats.comments:,}",
            f"{stats.blanks:,}",
            human_size(stats.size),
        ]
        if not args.no_bar:
            share = stats.lines / total.lines if total.lines else 0.0
            row.append(f"{render_bar(share, 16)} {share * 100:4.1f}%")
        rows.append(row)

    total_row = [
        "TOTAL",
        f"{total.files:,}",
        f"{total.lines:,}",
        f"{total.code:,}",
        f"{total.comments:,}",
        f"{total.blanks:,}",
        human_size(total.size),
    ]
    if not args.no_bar:
        total_row.append("")

    widths = [len(header) for header in headers]
    for row in rows + [total_row]:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    # Column index -> style, so the eye can find code and comment counts fast.
    column_styles = {0: "bright_cyan", 3: "bright_green", 4: "yellow",
                     5: "bright_black", 6: "dim", 7: "blue"}

    def pad(cell: str, index: int) -> str:
        return cell.ljust(widths[index]) if index == 0 else cell.rjust(widths[index])

    def plain_row(cells: list[str], *styles: str) -> str:
        text = "  ".join(pad(cell, index) for index, cell in enumerate(cells)).rstrip()
        return paint(text, *styles) if styles else text

    def painted_row(cells: list[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            padded = pad(cell, index)
            style = column_styles.get(index)
            parts.append(paint(padded, style) if style else padded)
        return "  ".join(parts).rstrip()

    rule = paint("-" * (sum(widths) + 2 * (len(widths) - 1)), "bright_black")

    print(plain_row(headers, "bold"))
    print(rule)
    for row in rows:
        print(painted_row(row))
    print(rule)
    print(plain_row(total_row, "bold"))

    if args.top and len(items) > args.top:
        hidden = len(items) - args.top
        print(paint(f"({hidden} more {plural(hidden, 'language')} hidden, use --top 0 for all)", "bright_black"))

    print()
    language_count = len(result.languages)
    summary = (
        f"{language_count} {plural(language_count, 'language')}, "
        f"{total.files:,} {plural(total.files, 'file')}, "
        f"{total.lines:,} lines, {total.code:,} code, "
        f"{comment_ratio(total):.1f}% comments"
    )
    print(paint(summary, "bold"))
    print(paint(f"scanned in {result.duration:.2f}s", "bright_black"))

    notes = []
    if result.skipped_unknown:
        by_ext = result.unknown_by_extension()
        head = ", ".join(f"{ext} x{count}" for ext, count in by_ext[:4])
        if len(by_ext) > 4:
            head += ", ..."
        notes.append(f"{result.skipped_unknown} unrecognized ({head})")
    if result.skipped_binary:
        notes.append(f"{result.skipped_binary} binary")
    if result.skipped_large:
        notes.append(f"{result.skipped_large} over size limit")
    if notes:
        print(paint("skipped: " + "; ".join(notes), "bright_black"))
    if result.skipped_unknown and not args.show_unknown:
        print(paint("run with --show-unknown to see which files those are", "bright_black"))


def comment_ratio(stats: Stats) -> float:
    documented = stats.code + stats.comments
    return (stats.comments / documented * 100) if documented else 0.0


def print_files(result: ScanResult, args: argparse.Namespace, paint: Palette) -> None:
    entries = sorted(result.files, key=lambda entry: entry.stats.lines, reverse=not args.ascending)
    limit = args.per_file if args.per_file and args.per_file > 0 else len(entries)
    entries = entries[:limit]

    if not entries:
        return

    path_width = max(len("File"), max(len(entry.path) for entry in entries))
    lang_width = max(len("Language"), max(len(entry.language) for entry in entries))

    header = (
        f"{'File'.ljust(path_width)}  {'Language'.ljust(lang_width)}  "
        f"{'Lines':>7}  {'Code':>7}  {'Comment':>7}  {'Blank':>7}"
    )
    print(paint(header, "bold"))
    print(paint("-" * len(header), "bright_black"))
    for entry in entries:
        stats = entry.stats
        print(
            f"{paint(entry.path.ljust(path_width), 'bright_cyan')}  "
            f"{entry.language.ljust(lang_width)}  "
            f"{stats.lines:>7,}  {paint(f'{stats.code:>7,}', 'bright_green')}  "
            f"{paint(f'{stats.comments:>7,}', 'yellow')}  "
            f"{paint(f'{stats.blanks:>7,}', 'bright_black')}"
        )
    print()


def print_unknown(result: ScanResult, paint: Palette, limit: int = 10) -> None:
    """Explain what the scan left out, so missing languages can be traced."""
    if not result.unknown_files and not result.skipped_dirs:
        print(paint("Every file in the tree was recognized.", "bold"))
        print()
        return

    if result.unknown_files:
        by_ext = result.unknown_by_extension()
        print(paint(f"Unrecognized files ({len(result.unknown_files)})", "bold"))
        print(paint("add an extension to LANGUAGE_MAP to start counting these",
                    "bright_black"))
        print(paint("-" * 60, "bright_black"))
        examples = defaultdict(list)
        for path in result.unknown_files:
            ext = os.path.splitext(path)[1].lower() or "(no extension)"
            examples[ext].append(path)
        for ext, count in by_ext:
            print(f"{paint(ext.ljust(16), 'bright_cyan')} {count:>5} "
                  f"{plural(count, 'file')}")
            for path in examples[ext][:limit]:
                print(paint(f"    {path}", "bright_black"))
            if count > limit:
                print(paint(f"    ... and {count - limit} more", "bright_black"))
        print()

    if result.skipped_dirs:
        names = sorted({os.path.basename(path) for path in result.skipped_dirs})
        print(paint(f"Skipped directories ({len(result.skipped_dirs)})", "bold"))
        print(paint("-" * 60, "bright_black"))
        print(paint("  " + ", ".join(names), "bright_black"))
        print(paint("  these came from IGNORE_DIRS, .gitignore, --exclude or the "
                    "hidden-file rule", "bright_black"))
        print(paint("  use --no-defaults, --no-gitignore or --include-hidden to "
                    "count them", "bright_black"))
        print()


def to_dict(result: ScanResult, include_files: bool) -> dict:
    def stats_dict(stats: Stats) -> dict:
        return {
            "files": stats.files,
            "lines": stats.lines,
            "code": stats.code,
            "comments": stats.comments,
            "blanks": stats.blanks,
            "chars": stats.chars,
            "bytes": stats.size,
        }

    payload = {
        "root": result.root,
        "generated_by": f"codestats {__version__}",
        "duration_seconds": round(result.duration, 4),
        "languages": {
            language: stats_dict(stats)
            for language, stats in sort_languages(result.languages, "lines", True)
        },
        "total": stats_dict(result.total),
        "skipped": {
            "unrecognized": result.skipped_unknown,
            "binary": result.skipped_binary,
            "too_large": result.skipped_large,
            "unrecognized_extensions": dict(result.unknown_by_extension()),
        },
    }
    if include_files:
        payload["files"] = [
            {"path": entry.path, "language": entry.language, **stats_dict(entry.stats)}
            for entry in sorted(result.files, key=lambda e: e.stats.lines, reverse=True)
        ]
    return payload


def write_csv(result: ScanResult, include_files: bool) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    if include_files:
        writer.writerow(["path", "language", "lines", "code", "comments", "blanks", "chars", "bytes"])
        for entry in sorted(result.files, key=lambda e: e.stats.lines, reverse=True):
            stats = entry.stats
            writer.writerow([
                entry.path, entry.language, stats.lines, stats.code,
                stats.comments, stats.blanks, stats.chars, stats.size,
            ])
        return

    writer.writerow(["language", "files", "lines", "code", "comments", "blanks", "chars", "bytes"])
    for language, stats in sort_languages(result.languages, "lines", True):
        writer.writerow([
            language, stats.files, stats.lines, stats.code,
            stats.comments, stats.blanks, stats.chars, stats.size,
        ])
    total = result.total
    writer.writerow([
        "TOTAL", total.files, total.lines, total.code,
        total.comments, total.blanks, total.chars, total.size,
    ])


# ==========================================================================
# CLI
# ==========================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codestats",
        description="Count files, lines, code, comments and blanks per language.",
        epilog="Examples:\n"
               "  python codestats.py\n"
               "  python codestats.py ../myapp --top 10\n"
               "  python codestats.py --exclude 'tests/*' --exclude '*.generated.*'\n"
               "  python codestats.py --only '*.py' --per-file 20\n"
               "  python codestats.py --json > stats.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: current directory)")

    output = parser.add_argument_group("output")
    output.add_argument("--json", action="store_true", help="print JSON instead of a table")
    output.add_argument("--csv", action="store_true", help="print CSV instead of a table")
    output.add_argument("--per-file", nargs="?", type=int, const=0, default=None,
                        metavar="N", help="also list per-file counts (optionally only the top N)")
    output.add_argument("--top", type=int, default=None, metavar="N",
                        help="show only the top N languages (0 for all)")
    output.add_argument("--sort", choices=sorted(SORT_KEYS), default="lines",
                        help="column to sort languages by (default: lines)")
    output.add_argument("--ascending", action="store_true", help="sort smallest first")
    output.add_argument("--no-bar", action="store_true", help="drop the share column")
    output.add_argument("--show-unknown", action="store_true",
                        help="list the files and directories the scan left out")
    output.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="when to use colored output (default: auto)")

    filters = parser.add_argument_group("filters")
    filters.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                         help="skip paths matching this glob (repeatable)")
    filters.add_argument("--only", action="append", default=[], metavar="GLOB",
                         help="count only paths matching this glob (repeatable)")
    filters.add_argument("--ignore-dir", action="append", default=[], metavar="NAME",
                         help="extra directory name to skip (repeatable)")
    filters.add_argument("--ignore-file", action="append", default=[], metavar="NAME",
                         help="extra exact file name to skip (repeatable)")
    filters.add_argument("--ignore-ext", action="append", default=[], metavar="EXT",
                         help="extra extension to skip, e.g. .log (repeatable)")
    filters.add_argument("--no-gitignore", action="store_true", help="ignore .gitignore rules")
    filters.add_argument("--no-defaults", action="store_true",
                         help="start from an empty ignore list instead of the built-in one")
    filters.add_argument("--include-hidden", action="store_true", help="count dotfiles and dot-directories")
    filters.add_argument("--max-size", type=float, default=None, metavar="MB",
                         help="skip files larger than this many megabytes")
    filters.add_argument("--follow-links", action="store_true", help="follow symlinked directories")

    parser.add_argument("--version", action="version", version=f"codestats {__version__}")
    return parser


def build_filters(args: argparse.Namespace) -> Filters:
    if args.no_defaults:
        ignore_dirs: set[str] = {".git"}
        ignore_files: set[str] = set()
        ignore_exts: set[str] = set()
    else:
        ignore_dirs = set(IGNORE_DIRS)
        ignore_files = set(IGNORE_FILES)
        ignore_exts = set(IGNORE_EXTS)

    ignore_dirs |= set(args.ignore_dir)
    ignore_files |= set(args.ignore_file)
    ignore_exts |= {ext if ext.startswith(".") else f".{ext}" for ext in args.ignore_ext}

    return Filters(
        ignore_dirs=ignore_dirs,
        ignore_files=ignore_files,
        ignore_exts=ignore_exts,
        exclude_globs=list(args.exclude),
        include_globs=list(args.only),
        include_hidden=args.include_hidden,
        max_bytes=int(args.max_size * 1024 * 1024) if args.max_size else None,
        gitignore=None if args.no_gitignore else GitIgnore(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.json and args.csv:
        parser.error("choose either --json or --csv, not both")

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"codestats: '{args.path}' is not a directory", file=sys.stderr)
        return 2

    if args.top == 0:
        args.top = None

    result = scan(root, build_filters(args), follow_links=args.follow_links)

    if args.json:
        print(json.dumps(to_dict(result, include_files=args.per_file is not None), indent=2))
        return 0
    if args.csv:
        write_csv(result, include_files=args.per_file is not None)
        return 0

    paint = Palette(should_colorize(args.color))

    if not result.languages:
        print("No recognized source files found.")
        print("Try --show-unknown to see what was skipped, or --include-hidden,")
        print("--no-defaults, or add extensions to LANGUAGE_MAP.")
        if args.show_unknown:
            print()
            print_unknown(result, paint)
        return 0

    print(paint(f"codestats {__version__}", "bold") + paint(f"  {root}", "bright_black"))
    print()
    if args.show_unknown:
        print_unknown(result, paint)
    if args.per_file is not None:
        print_files(result, args, paint)
    print_table(result, args, paint)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
