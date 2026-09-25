import os
import pytest
from backend.scanner.walker import FileWalker

def test_file_walker_skips_and_counts(tmp_path):
    # Setup our own temporary test environment or use the fixtures directory.
    # The instructions say to test against fixtures/python_sample/.
    # Since we are running from project root (presumably), let's use the relative path or an absolute one.
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    fixture_dir = os.path.join(current_dir, 'fixtures', 'python_sample')
    
    walker = FileWalker()
    files = walker.walk(fixture_dir)
    
    # Extract just the filenames or paths for easy assertion
    returned_paths = [f.path.replace(os.sep, '/') for f in files]
    
    # main.py and .gitignore should be returned
    # ignored.py should be skipped (.gitignore)
    # node_modules/index.js should be skipped (SKIP_DIRS)
    # image.png should be skipped (binary file)
    
    # Let's see if ignored.py was correctly skipped
    assert not any('ignored.py' in p for p in returned_paths), "ignored.py should be skipped by .gitignore"
    
    # Assert node_modules is skipped
    assert not any('node_modules' in p for p in returned_paths), "node_modules should be skipped"
    
    # Assert image.png is skipped
    assert not any('image.png' in p for p in returned_paths), "image.png should be skipped as binary"
    
    # Should include main.py and .gitignore
    assert any('main.py' in p for p in returned_paths)
    assert any('.gitignore' in p for p in returned_paths)

    # We expect exactly 2 files
    assert len(files) == 2
