"""Make a sweep copy of a bot with overridden params.h constants.
python tools/variant.py bots/v1 bots/v1_bank20 BANK_AT=20 GOLD_W=0.1"""
import re, shutil, sys, pathlib
src, dst, *kv = sys.argv[1:]
dst = pathlib.Path(dst)
if dst.exists(): shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.cambc'))
p = dst / 'src' / 'params.h'
s = p.read_text()
for item in kv:
    k, v = item.split('=')
    s, n = re.subn(rf'(\b{k}(?:\[\])?\s*=\s*)[^;]+;', lambda m: m.group(1) + v + ';', s)
    if not n: sys.exit(f'no param {k}')
p.write_text(s)
print('made', dst)
