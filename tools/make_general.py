"""bots/g65 = v65 as ONE general bot for training: map identity never used (settings live in the Map::unknown case), draft honours an explicit draft.
python tools/make_general.py [src_bot=v65] [dst_bot=g65]"""
import pathlib, shutil, sys, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
src, dst = sys.argv[1] if len(sys.argv) > 1 else 'v65', sys.argv[2] if len(sys.argv) > 2 else 'g65'
D = ROOT / 'bots' / dst
shutil.rmtree(D, ignore_errors=True); shutil.copytree(ROOT / 'bots' / src, D, ignore=shutil.ignore_patterns('.cambc', 'compile_commands.json'))
p = D / 'src' / 'map_strategy.h'; s = p.read_text()
a = "inline map_policies::Map identify() {\n"
assert s.count(a) == 1
s = s.replace(a, a + "    return map_policies::Map::unknown;   // general bot: the map pool changes every patch, settings are one global block\n")
a = "inline map_policies::Map current_map() {\n"
assert s.count(a) == 1
s = s.replace(a, a + "    return map_policies::Map::unknown;\n")
p.write_text(s)
p = D / 'src' / 'draft.cpp'; s = p.read_text()
a = "    static const auto profile=map_policies::for_map(map_strategy::identify());\n"
assert s.count(a) == 1
s = s.replace(a, a + "    if(profile.explicit_draft)return std::vector<int>(profile.draft.begin(),profile.draft.end());   // trained draft order\n")
p.write_text(s)
# empty general tuning block (defaults) in the standard schema
(D / 'tuning.json').write_text(json.dumps({"maps": {}}, indent=1))
for h in ('map_tuning.h', 'policy_tuning.h'):
    f = D / 'src' / h; t = f.read_text()
print('created', D)
