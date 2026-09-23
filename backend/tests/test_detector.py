import os
import pytest
from backend.scanner.detector import LanguageDetector
from backend.scanner.symbols import FileInfo

@pytest.fixture
def detector():
    return LanguageDetector()

def create_file_info(path: str) -> FileInfo:
    return FileInfo(path=path, size_bytes=100, language='', is_binary=False)

def test_language_detector_extensions(detector):
    assert detector.detect(create_file_info("test.py")) == "Python"
    assert detector.detect(create_file_info("main.ts")) == "TypeScript"
    assert detector.detect(create_file_info("app.js")) == "JavaScript"
    assert detector.detect(create_file_info("Server.java")) == "Java"
    assert detector.detect(create_file_info("main.go")) == "Go"
    assert detector.detect(create_file_info("lib.rs")) == "Rust"
    assert detector.detect(create_file_info("util.c")) == "C"
    assert detector.detect(create_file_info("math.cpp")) == "C++"
    assert detector.detect(create_file_info("unknown.txt")) == "unknown"

def test_language_detector_shebang_python(detector, tmp_path):
    script_path = tmp_path / "script1"
    script_path.write_text("#!/usr/bin/env python3\nprint('hello')", encoding='utf-8')
    assert detector.detect(create_file_info(str(script_path))) == "Python"

def test_language_detector_shebang_node(detector, tmp_path):
    script_path = tmp_path / "script2"
    script_path.write_text("#!/usr/bin/env node\nconsole.log('hello')", encoding='utf-8')
    assert detector.detect(create_file_info(str(script_path))) == "JavaScript"

def test_language_detector_no_shebang(detector, tmp_path):
    script_path = tmp_path / "script3"
    script_path.write_text("just some text", encoding='utf-8')
    assert detector.detect(create_file_info(str(script_path))) == "unknown"
