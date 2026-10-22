import unittest

from backend.review.blast_radius import BlastRadiusEngine
from backend.scanner.import_tracker import FileImportMap


class TestBlastRadiusEngine(unittest.TestCase):
    def test_finds_direct_and_indirect_dependents(self):
        maps = {
            "a.py": FileImportMap(
                file_path="a.py", language="Python"
            ),
            "b.py": FileImportMap(
                file_path="b.py",
                language="Python",
                local_dependencies=["a.py"],
            ),
            "c.py": FileImportMap(
                file_path="c.py",
                language="Python",
                local_dependencies=["b.py"],
            ),
        }

        result = BlastRadiusEngine().compute(["a.py"], maps)

        self.assertEqual(result["affected_files"], ["b.py", "c.py"])
        self.assertEqual(result["total_affected"], 2)


if __name__ == "__main__":
    unittest.main()
