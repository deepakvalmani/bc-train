# General-bot trainer (tools/gtrain.py) — how to run it

One global settings block for ALL maps (the pool changes every patch; per-map training of 40 maps is too slow and overfits).

## What is trained (bots/g65 = v65 with map identity switched off)
- **199 numeric/bool fields** from `bots/g65/src/tune_fields.txt` (85 int, 76 bool, 37 float, 16 double; 15 fuel/debug fields are excluded): camp choice (GEM_W, GOLD_W, JOIN_MULT, SQUAD_SOAK, TEAM_SOAK ...), banking (BANK_AT, BANK_NEAR ...), recall/shop (RECALL_HP, SHOP_GOLD ...), fighting (LANCH_*, KITE, CHASE, BURST_EXIT, AOE_PVP ...), retreat/flee, wards, shop.
- **13 policy fields**: clear_rate, gold_only_scale, near_k, death_memory, lone_flee, lone_foes, rally, respawn_gate, home_only, gate_buddies, spiral_deaths, flee_outnumbered, solo_capture.
- **Champion draft order** (12 champions incl. Heart of Ruin; each champion tried at positions 1-4).
- First pass = **452 single-change candidates** (386 tune, 22 policy, 44 draft); accepted changes make new candidates (values are halved/doubled again), so later passes continue from the new settings.

## How it works
- **Lanes** (default = number of CPU cores): each lane is its own copy of the runtime (about 110 MB) and tests one candidate at a time: build (about 35 s) then its games. 8 cores = 8 candidates at once.
- **Three stages**, all deterministic (a game result never changes, so an accepted candidate's own scores become the new baseline, no re-measure):
  - **S0** quick screen: 4 maps x 1 sparring bot x 2 sides = 8 games. Must not lose.
  - **S1** train: 8 maps (eight, corners, lanes, fragment, hooks, starfish, gold-rush, the-farm) x 2 bots (v63, v1.0.0) x 2 sides = 32 games. Must beat the baseline by the margin (win rate, then score).
  - **S2** confirm: 8 other maps (collision, swirl, islands, corridors, shortcut, starvation, gemfight, great-wall) x 3 other bots (v64, v53_3, v46cloud) x 2 sides = 48 games. Must not get worse.
- **Score** = win rate, then gems minus 60 x (our deaths - kills) plus 150 x gems/round (rewards survival and speed).
- Resumable: stop with Ctrl-C and rerun the same command (tested candidates are remembered in `tuning.json`).
- Results: `bots/g65/tuning.json` (map "general") + generated headers, so `tools/bundle.py` works as before.

## Run it (Windows PowerShell or bash, same commands)
Prerequisites (this machine already has them): the runtime folder `rt_v4` (CLI 3.0.4, engine 1.0.2, all maps; create with `cambc init --yes rt_v4` and copy `cambc.exe` into it), and the opponent bots `v63, v1.0.0, v64, v53_3, v46cloud` under `bots/`. Check: `CAMBC_HOME=rt_v4 python tools/build_check.py bots/g65` prints `rc 0 errors 0`.

```bash
# 1. (optional) the trainer creates bots/g65_train from bots/g65 by itself on the first run
# 2. start (10 hours, all cores). Use --lanes N to leave some CPU free (cores/2 is comfortable on a desktop you also use)
python -u tools/gtrain.py bots/g65_train --hours 10 --lanes 6
# watch:  out/gt/g65_train/train.log   (lines: ACCEPT / reject / drop / progress)
# 3. final check on EVERY map in the pool: trained bot vs the untrained start (about 40 min)
python -u tools/gtrain.py bots/g65_train --final --lanes 6
# 4. package (always with this script) and upload by hand
python tools/bundle.py bots/g65_train g65_trained        # -> submissions/g65_trained.zip
```

### Several machines (optional)
Each machine takes a disjoint half of the fields, then merge:
```bash
python -u tools/gtrain.py bots/g65_a --hours 10 --shard 0/2      # machine A
python -u tools/gtrain.py bots/g65_b --hours 10 --shard 1/2      # machine B
python -u tools/gtrain.py bots/g65 --merge-from bots/g65_a,bots/g65_b --lanes 6   # applies every change one by one, keeps those that do not hurt S1+S2
```

## Rules
- One trainer per bot folder. Do not run other heavy programs meanwhile (games time out and are dropped).
- Local sparring bots cannot punish deaths the way top teams do: after training, upload and run `python tools/ladder_round.py --top 10 ...` to judge. Compare deaths and gems with the v65 round (1/100 wins, 30 deaths, 174 gems per game).
- Change the maps/opponents with `--s1-maps`, `--s1-opps`, `--s2-maps`, `--s2-opps` (names of files in the runtime `maps/` and bot folders under `bots/`). The 5 new maps (gem-fields, gemfight, great-wall, lost-world, road-of-riches) are in S2/final.
- Smoke test (5 minutes): `python tools/gtrain.py bots/gtest --lanes 2 --hours 0.5 --max-candidates 4 --s0-maps 00eight --s1-maps 00eight,00corners --s1-opps v63 --s2-maps 00lanes --s2-opps v64` (after `cp -r bots/g65 bots/gtest`).
