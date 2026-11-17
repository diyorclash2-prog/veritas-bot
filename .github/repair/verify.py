"""Trusted test runner; the CI container has no network, secrets or writable source."""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

candidate, baseline = (p.resolve() for p in map(Path,sys.argv[1:3])) if len(sys.argv)==3 else (Path('/candidate'),Path('/trusted'))
auto = os.getenv('AUTOREPAIR') == 'true'
editable = {'bot.py','lingua_bot_bridge.py','super_settings.py'}

def files(root):
    return {str(p.relative_to(root)): p for p in root.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.parts}

before, after = files(baseline), files(candidate)
if auto:
    changed = {name for name in before.keys() | after.keys()
               if name not in before or name not in after or before[name].read_bytes()!=after[name].read_bytes()}
    tests = [name for name in changed if re.fullmatch(r'test_repair_case_[a-z0-9_]+\.py',name)]
    assert tests and len(changed)<=6, 'Expected a regression test and bounded changes'
    for name in changed:
        assert name in after and not after[name].is_symlink(), 'Deleted or symlink file'
        assert name in editable or (name in tests and name not in before), 'Protected file changed'
        ast.parse(after[name].read_text(),filename=name)
else:
    tests = []

for name, path in after.items():
    if name.endswith('.py') and '/' not in name:
        ast.parse(path.read_text(),filename=name)

# The subprocess is still inside the unprivileged, network-disabled container.
runner = '''import sys,unittest
sys.path.insert(0,sys.argv[1])
loader=unittest.TestLoader()
suite=unittest.TestSuite()
for filename in sys.argv[2:]:
 import importlib.util
 spec=importlib.util.spec_from_file_location(filename.rsplit('/',1)[-1][:-3],filename)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 suite.addTests(loader.loadTestsFromModule(module))
result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.testsRun and result.wasSuccessful() else 1)
'''
if tests:
    # __file__-relative AST tests must inspect OLD source too. Merely changing
    # sys.path leaves the test located beside candidate/bot.py and tests the
    # candidate twice. Overlay only the new tests onto a disposable baseline.
    # Both checkouts stay untouched; this still runs inside the isolated CI container.
    with tempfile.TemporaryDirectory(prefix='veritas-baseline-') as tmp:
        prior_root = Path(tmp)
        for name, path in before.items():
            assert not path.is_symlink(), 'Symlink in baseline'
            target = prior_root/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,target)
        for name in tests:
            shutil.copyfile(candidate/name,prior_root/name)
        prior = subprocess.run([sys.executable,'-I','-c',runner,str(prior_root),
                                *[str(prior_root/t) for t in sorted(tests)]],
                               cwd=prior_root,timeout=120)
    assert prior.returncode == 1, 'Regression must fail on the old code'
all_tests = sorted(str(p) for p in candidate.glob('test_*.py'))
assert all_tests, 'No tests found'
result = subprocess.run([sys.executable,'-I','-c',runner,str(candidate),*all_tests],cwd=candidate,timeout=180)
sys.exit(result.returncode)
