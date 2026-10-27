import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, OUTPUT

SPEC = importlib.util.spec_from_file_location("public_files", ROOT/"scripts/check_public_files.py")
scanner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scanner)


@unittest.skipUnless(shutil.which("git"), "requires git")
class PublicFilesTests(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True,exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.mock_root = patch.object(scanner,"ROOT",self.root)
        self.mock_root.start()
        self.addCleanup(self.mock_root.stop)
        self.git("init", "-q")

    def git(self,*args):
        return subprocess.run(["git",*args],cwd=self.root,check=True,capture_output=True)

    def test_staged_credential_is_found_even_if_worktree_is_clean(self):
        readme = self.root/"README.md"
        readme.write_text("ghp_" + "A"*30)
        self.git("add","README.md")
        readme.write_text("safe public text")
        issues = scanner.inspect_index()
        self.assertEqual(issues[0]["kind"], "index_github_credential")
        self.assertNotIn("A"*30,str(issues))

    def test_forced_private_runtime_in_index_is_rejected(self):
        private = self.root/".publisher-runs/private.json"
        private.parent.mkdir()
        private.write_text("private run")
        self.git("add","-f",".publisher-runs/private.json")
        self.assertEqual(scanner.inspect_index()[0]["kind"],"unsafe_index_entry")

    def test_public_text_passes_in_worktree_and_index(self):
        (self.root/"README.md").write_text("public docs")
        self.git("add","README.md")
        self.assertEqual(scanner.inspect(scanner.candidates()),[])
        self.assertEqual(scanner.inspect_index(),[])
