"""Build the readable bot-design guide and compact downloadable report package."""
import csv
import json
import zipfile
import hashlib
from datetime import datetime,timezone
from pathlib import Path
from corpus_report import OUT,ROOT,table

def csv_rows(name):
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
    summary=json.loads((OUT/'summary.json').read_text())
    coverage=json.loads((OUT/'coverage.json').read_text())
    if not coverage['complete']:raise ValueError('Full coverage and integrity audit required before publication')
    validation=json.loads((OUT/'validation.json').read_text())
    if not validation['passed']:raise ValueError('Independent validation is incomplete or failed')
    comparisons=csv_rows('winner_loser.csv');leads=csv_rows('early_leads.csv');drafts=csv_rows('drafts.csv');champions=csv_rows('champions.csv')
    opening=csv_rows('opening_summary.csv') if (OUT/'opening_summary.csv').exists() else []
    targeting=csv_rows('combat_selection_summary.csv') if (OUT/'combat_selection_summary.csv').exists() else []
    execution=[r for r in csv_rows('execution.csv') if r['clean']=='1']
    primary=[r for r in comparisons if r['subset']=='clean']
    select=lambda name:next(r for r in primary if r['metric']==name)
    early=[r for r in leads if r['subset']=='clean' and r['round'] in ['100','300']]
    preferred=[]
    for m in sorted({r['map'] for r in drafts}):
        candidates=[r for r in drafts if r['subset']=='clean' and r['map']==m and int(r['nonmirror_games'])>=30]
        candidates.sort(key=lambda r:(-float(r['nonmirror_win_pct']),-int(r['nonmirror_games'])))
        preferred.extend(candidates[:3])
    lines=['# What the replay corpus says to build','',
           f"This guide covers **{coverage['expected']:,} match IDs**, representing **{coverage['unique_analyzed']:,} distinct replay contents** from the first folder, replays-2026-10-18-part1, only. All IDs have evidence and a review; identical replay contents are counted once in the primary statistical tables.",
           f"The main strategy comparison uses **{summary['subsets']['clean']:,} productive games that ended at 1,000 gems and had no recorded bot error or fuel rollover on either side**. Of those, {summary['subsets']['mirrored']:,} have identical physical champion lineups. Gold-tiebreak games cannot drive this primary comparison. Read REPORT.md for all cohorts, definitions and the limitations of observational comparisons.",
           '', '## Measured winning patterns','',
           'These are paired measurements from opponents in the same clean game. Their association with winning does not prove that increasing a counter will improve a bot. In particular, bank totals and lifetime resources partly reflect the outcome itself.', '',
           table([select(k) for k in ['death_episodes','early_deaths','captures','unique_camps','gold','gold_spent','camp_damage','casts','attacks','move_pct','camp_pct','dead_pct','focus_shard_eq','strength_shard_eq','health_shard_eq']],
                 [('Metric','metric'),('Winner median','winner_median'),('Loser median','loser_median'),('Median paired difference','paired_difference_median'),('Non-tied games','non_tied_pairs'),('Higher value wins %','higher_value_wins_pct')]),
           '', 'The same comparison with identical physical lineups is below. This removes lineup differences within each game, while policy strength, starting side and repeated anonymous bots remain uncontrolled.', '',
           table([r for r in comparisons if r['subset']=='mirrored' and r['metric'] in ['death_episodes','captures','gold','casts','attacks','move_pct','camp_pct','focus_shard_eq']],
                 [('Metric','metric'),('Winner median','winner_median'),('Loser median','loser_median'),('Median paired difference','paired_difference_median'),('Non-tied games','non_tied_pairs'),('Higher value wins %','higher_value_wins_pct')]),
           '', '## Timing: what is already different early','',
           'Compare early economy and survival at equal rounds before interpreting a late equipment or score advantage. Higher-death rows should be read in the opposite direction from resource rows. These estimates exclude ties and games that ended before the checkpoint.', '',
           table(early,[('Round','round'),('Metric with higher value','feature'),('Games','non_tied_games'),('Eventual win %','higher_value_win_pct'),('95% interval','ci95')]),
           '', 'The close readings in CASE_STUDIES.md show a no-death mirror-draft race decided by farming and delivery timing, and Contest gold farming that failed to secure gem-producing objectives. These mechanisms require different decisions.',
           '', '## Movement and objective selection','',
           'Separate four decisions: whether to take a fight, which camp/objective to work toward, which legal move or action to perform this turn, and when/where to bank. Choosing a good destination does not repair a poor move-versus-cast decision.',
           '', 'Observed opening formations in clean games follow. won=1 means the eventual winner, 0 the loser. The front body is the living body geometrically nearest any living enemy. pre_first_contact is the preceding round, available only for contact in r2–61. Nearby support ignores walls, vision and cooldowns; it is not proof of effective help. HP sums and spread also depend on the draft.', '',
           table(opening,[('Checkpoint','checkpoint'),('Won','won'),('Team samples','games'),('Living bodies','living_bodies'),('Front allies ≤4','front_allies4'),('Front allies ≤8','front_allies8'),('Mean allies ≤8','average_allies8'),('Distance from start','mean_distance_from_initial_tile')]),
           '', 'A useful starting model to test is:', '',
           '```text\nobjective_value = (expected_gems * probability_of_safe_delivery\n                   + temporary_gold_value * expected_gold)\n                  / (path_turns + clear_turns + capture_turns + allocated_bank_time)\n                  - expected_death_cost\n```', '',
           'This is a proposed decision model, not a formula recovered from an opponent. Use real path distances through walls, holes and occupied tiles. Recompute a small legal move set each turn; cache static map geometry. Include the current equipment and cooldowns in clear-time estimates. Gold value should change as it creates damage/survival upgrades, while a late-game bot near the winning score should prioritize feasible tributes.',
           '', 'Ordinary movement is eight-directional and one tile. Ranged champions normally share their ordinary movement/basic-attack allowance; several damaging spells also exclude walking. Evaluate the valuable stand-and-cast or stand-and-attack option before spending that allowance. Melee units normally retain their attack after walking. Dash and attack-reset kits have exceptions: consult legal API predicates, then select among complete legal action sequences.',
           '', 'First contact in the data is geometric distance eight, not proof of mutual vision. Walls and bushes matter. Treat missing enemies as uncertainty; nearby allies are useful only if they can arrive or act in time. A blocked step against a previously unseen occupant preserves the movement allowance, so a bounded retry can be useful. Count and cap retries to preserve fuel.',
           '', '## Camp farming, capture allocation and map rules','',
           'On Contest, all groups except the two monoliths produce zero gems. The inspected 90-versus-34-capture loss is the clearest warning against rewarding generic capture count. Distinguish raw camp count, gold production, gem production, stolen gems and completed tributes.',
           '', 'The local rules give these base rewards and costs:', '',
           '| Camp | HP | Gems | Gold | Base respawn |\n| --- | --- | --- | --- | --- |\n| Wolf | 1,350 | 22 | 90 | 40 |\n| Elk | 2,400 | 36 | 160 | 60 |\n| Gem cluster | 500 | 24 | 0 | 50 |\n| Gold cluster | 500 | 0 | 35 | 50 |\n| Monolith | 20,000 | 200 | 300 | 150 |',
           '', 'After clearing a group, one body must occupy one of its original monster tiles uncontested. More allies do not accelerate the five-round timer. The observed clear-to-capture lag also includes getting onto the tile and the capture phase ordering; see routes.csv. Rewards split among bodies present at completion. That permits intentional reward allocation to a carry, but fighters excluded from rewards will need another income source. There is no later gem or HP transfer between bodies.',
           '', 'Keep one safe capturer when extra bodies can work elsewhere. Do not blindly split into isolated camps under enemy pressure: death exposure can dominate the saved travel time. Capture resets, unclaimed rewards, time spent waiting on a respawning group, and repeated re-clearing of a small home circuit are distinct losses. routes.csv contains each side’s first eight captures, group reuse and clear-to-capture delay; the review ZIP contains the entire capture order.',
           '', '## Combat execution and ability timing','',
           'Both slots share one successful cast per turn, but each slot has its own normal eight-turn-end cooldown. Measure each slot, legal targets and action sequences separately. A cooldown being zero while an enemy is within eight does not mean the spell is legal or worthwhile. execution.csv reports cadence and same-turn combinations; the per-game JSON records every cast and useful action sequence.',
           'A basic attack and a cast are separate allowances: a legal turn can contain both. In first-folder Lanes replay 00000b92-283b-4c7c-9289-85b61f74a2ba, B Cassi casts slot 0 and basic-attacks on r32. A non-reset damaging cast does not globally replace the basic attack. Excluding walking is a different restriction. This corrects the older “attack or cast” shorthand in the project handoff.',
           '', 'Actual execution cadence in clean games is below. won=1 denotes the winner. Rates use all alive rounds, including travel and capture; they are not percentages of legal combat opportunities. Cast gaps mix camp fighting, PvP, travel and banking. Reset sequences count adjacent attack → cast → attack actions.', '',
           table(execution,[('Champion','champion'),('Won','won'),('Bodies sampled','games'),('Basics /100 alive rounds','attacks_per_100_alive_rounds'),('Slot 0 /100','casts_0_per_100_alive_rounds'),('Slot 1 /100','casts_1_per_100_alive_rounds'),('Slot 0 gap','cast_gap_median_0'),('Slot 1 gap','cast_gap_median_1'),('Reset sequences /100','attack_cast_attack_sequences_per_100_alive_rounds')]),
           '', '- **Stellar:** single target is 2×Focus; radius-one area damage is 1.4×Focus per target. Two valid targets give 2.8×Focus total, exceeding 2×Focus, but killing one dangerous target can still be better. Include camp targets as well as champions. Both damaging spells exclude walking.',
           '- **Prism:** targeted 1.5×Focus damage plus stun, or radius-one 1×Focus per target. Carried gems add 0.2 Focus each; banking removes that bonus. Keeping gems buys temporary combat power at the cost of delivery delay and theft exposure.',
           '- **Cassi/Issac:** Cassi has 2×Focus damage and a separate compatible stun. Issac has attack reset and dash. One death kills both bodies and loses both bags. Partner danger is a joint state, not two independent low-HP thresholds.',
           '- **Ryth:** area damage/stun and attack reset. Bonus HP adds Strength. Use the area stun for prevention and target control, not just raw damage.',
           '- **Varg:** basic attacks splash full Strength to other valid targets around the primary target. Target placement and reset sequences can be worth more than attacking the nearest monster. His shield is 2.5×Focus for five turns.',
           '- **Ren:** targeted damage/stun, dash and 0.2×Focus retaliation per incoming hit. Focus contributes to retaliation as well as the spell, and retaliation may trigger as he dies. A naive DPS/headcount comparison misses this.',
           '- **Vendetta:** camp and champion kills refresh spell cooldowns. Shorter-than-eight cast gaps can be legitimate. This does not remove the one-cast-per-turn limit; use the refresh on the next legal opportunity.',
           '- **Vesper Vale:** attack reset, dash and 20% bonus gold; Treasure adds another 20 percentage points. Her income and attack execution must be assessed together.',
           '- **Marcella:** stun immunity, a reset that enhances the next attack with a stun, and 2×Focus targeted damage. Do not plan to disable her with a stun.',
           '- **Tavi:** can buy shards in the field, so income can turn into power without a shop return. Field Health increases max HP without healing. His 2.2×Focus spell also stuns.',
           '- **Willow:** heals another ally for up to 3×Focus; cannot self-heal with that spell. Evaluate saved body-turns and bags, not only damage dealt.',
           '', 'A useful bounded micro planner tests legal attack → reset → attack sequences, compatible movement, a cast that prevents lethal damage, and high-value area targets. It must also account for camp aggro: damaging a monster awakens it, and camps act before the following champion turns. Do not open multiple camps without a credible HP budget.',
           '', 'Observed basic-attack targeting in clean games with at least five champion-directed basics per team is below. Each row summarizes per-team fractions; sample counts can differ by winning side. Focus means at least two distinct allied bodies basic-attacked the same enemy in one round. Lowest HP compares only geometric basic range, so unseen targets, shields, retaliation, gems and stun value can justify a different choice. These are descriptive patterns, not a target-selection rule.', '',
           table(targeting,[('Won','won'),('Team samples','games'),('Multi-body focus fraction','multi_body_focus_fraction'),('Targets per PvP round','mean_distinct_targets_per_pvp_round'),('Lowest-HP fraction','lowest_hp_fraction'),('Target HP fraction','target_hp_fraction_median')]),
           '', '## Drafts: choose candidates to test, not an unconditional tier list','',
           'The following are the three highest observed clean nonmirror rates per map among lineups with at least 30 nonmirror appearances. They are candidate test sets. Opponent quality, policy and side remain confounders; an absent lineup may simply lack data. Cassi and Issac are listed as two bodies but consume one draft pick.', '',
           table(preferred,[('Map','map'),('Physical lineup','draft'),('Nonmirror games','nonmirror_games'),('Observed win %','nonmirror_win_pct'),('95% interval','nonmirror_ci95'),('Median death episodes','median_deaths')]),
           '', 'champions.csv includes clean and broader productive champion statistics. champion_maps.csv supplies exclusive champion associations separately by map. drafts.csv retains all observed lineups and sample sizes, including small samples omitted above. Do not convert a rare 100% record into a universal draft rule.',
           '', '## Equipment and economy','',
           'Look for income becoming usable strength early, not merely a large final inventory. Compare purchases and combat stats at equal rounds, rather than treating a winner’s larger final inventory as proof of a superior item order.',
           '', 'Compare economy.csv’s purchases by r100 with champion stats at r50/100/150/200/300. Focus has different returns across kits; attack-reset and splash users have different Strength returns. Health and damage reduction should be valued by the next encounter and saved farming time. Tavi changes the cost of returning to shop; Health bought on spawn heals the HP gained, while Tavi field purchases do not.',
           '', 'Five matching shards form an emblem. Power emblems provide six shards of stats for five shards of cost. End-inventory tables use purchase-equivalent units, so do not confuse those with effective stat growth. Explicit Tavi sale refunds are excluded from reconstructed income, and seller inventories are checked at both buys and sales. This income is still not a direct read of the official lifetime-gold tiebreak field.',
           '', '## Recall, tribute and finishing the game','',
           'A completed recall costs five owner turn-end ticks, or three with Home, and damage or stun interrupts it. Escape first. Arrival is at turn start; remaining on spawn through turn end gives the full heal. Starting a recall repeatedly is not evidence of repeated recovery: inspect cancellations and actual movement/state changes.',
           '', 'Tribute is different: duration is max(1, ceil(starting bag/10)) owner turn-end ticks, then completion at a later owner turn start. Damage does not cancel it; stun, death and a new opposing altar lock can. Completion banks the current bag, including gems acquired during the channel. Captures resolve before champion channels. Therefore coordinating a small initial tribute with an incoming capture reward is a rule-supported timing idea; short_bank_channels.csv flags observed candidates for exact inspection. Do not assume every short gap proves that tactic without checking the replay.',
           '', 'Plan a win from current score plus deliverable bags, not current score alone. The no-death Ambush case was losing 894–952 at r500, yet had two near-term deliveries that won at r507. Compare safe altar path, queue/occupancy, channel duration, enemy stun access and altar locks. Returning to the same altar out of habit can waste a route even when the bag size is sensible.',
           '', '## Vision, turn order, locks and teleports','',
           'Wards are personal vision: a new ward replaces the previous one, it persists, and allies do not share that vision automatically. Repositioning every round is not inherently good or bad. Value visibility at the next decision and the computation cost. Communicate compact, timestamped facts in the eight-byte shared match memory; keep static draft calculations in the separate draft memory.',
           '', 'Turn order alternates teams and the starting team alternates by round. Priority changes take effect next round. Stun and focus-fire value depend on whether a target is still due to act, and a late ally’s arrival can be too late to prevent a burst. Raw nearby headcount does not capture those differences. The replay telemetry does not recover opponents’ private priority policy or memory format.',
           '', 'Altar locks cost 10 gold, block opponents while allowing allies to tribute, cancel an existing opposing tribute, and take three basic attacks to clear. Attempting to tribute against one turns into attacks on it. Their effect is delay and denial, not simply number placed. Teleport crystals have range three, cross intervening terrain and channel for three owner turn ends; stun/death interrupts them, damage does not. Channel-start counts alone cannot establish completion or value.',
           '', '## Implementation and validation order','',
           '1. Make the bot reliably act inside the 100k fuel budget; cache camp/map data and bound every search. Check early useful actions and rollovers before tuning tactics.',
           '2. Implement legal, champion-specific action templates; measure both ability slots and reset/splash/area behavior.',
           '3. Add joint pair safety and a short-horizon incoming-damage/escape estimate; include unseen-enemy uncertainty and ally arrival timing.',
           '4. Build a map-specific reward and rotation policy, with capture completion and gem-producing objectives explicit.',
           '5. Turn rewards into useful equipment, allocate capture income deliberately, and schedule safe tributes toward the winning threshold.',
           '6. Change one mechanism at a time. Freeze sources, test both sides of all 17 maps against the last best and established references, and inspect faults, early milestones and death context. A ladder claim requires fresh ladder evidence; these anonymous replays cannot establish a new bot’s rating.',
           '', '## All evidence and reproducibility','',
           'The download package contains the first-folder reports, tables, source references and every Markdown game review. The larger turn-by-turn JSON evidence remains separately in the local games cache; game_reviews.csv points to each included compressed file. Only IDs in inventory.json belong to this analysis; the shared cache may retain excluded work from other folders.',
           '- REPORT.md: complete methods, comparisons, map tables, early leads, champion statistics and limitations.',
           '- CASE_STUDIES.md: close readings with match IDs and exact measurements.',
           '- game_reviews.zip: a review for every match ID; duplicate contents reference their identical review.',
           '- game_reviews.csv and the other CSVs: complete tabular results.',
           '- games/*.json.gz: detailed compressed action/event evidence. Open with Python gzip or any gzip-capable extractor.',
           '- inventory.json, coverage.json, duplicates.json and validation.json: exact inputs, source checksums, completeness and independent checks.',
           '- GameRules.md and BotAPICpp.md: the local official mechanics/champion reference and C++ API reference, included in the download package. These are references, not additional measured replay findings.',
           '', 'Reproduction requires the original first-folder archive in game_summaries, Python, Node with WASI support, and the installed official visualiser 0.0.3 assets identified by validation.json. Run `python tools/corpus_run.py`, then `python tools/corpus_report.py`, `python tools/corpus_patterns.py`, `python tools/corpus_validate.py`, and `python tools/corpus_publish.py`. No matches, bot source changes, uploads or account actions are involved.','']
    (OUT/'PLAYBOOK.md').write_text('\n'.join(lines),encoding='utf-8')
    files=[OUT/'PLAYBOOK.md',OUT/'REPORT.md',OUT/'CASE_STUDIES.md',OUT/'game_reviews.zip']
    files+=list(OUT.glob('*.csv'))
    files+=[OUT/n for n in ['coverage.json','inventory.json','duplicates.json','summary.json','validation.json','geometry.json','case_selection.json']]
    tools=['corpus_run.py','corpus_extract.mjs','corpus_report.py','corpus_patterns.py','corpus_geometry.mjs','corpus_validate.py','corpus_publish.py','corpus_finalize.py','inspect_website_replay.mjs','safeio.py']
    inventory=json.loads((OUT/'inventory.json').read_text())
    provenance=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        dataset_sha256=hashlib.sha256('\n'.join(sorted(r['id']+':'+r['sha256'] for r in inventory['records'])).encode()).hexdigest(),
        engine_sha256=validation['engine_sha256'],tools={n:hashlib.sha256((ROOT/'tools'/n).read_bytes()).hexdigest() for n in tools},
        references={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['GameRules.md','BotAPICpp.md']})
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2))
    files.append(OUT/'provenance.json');files.extend(ROOT/n for n in ['GameRules.md','BotAPICpp.md'])
    with zipfile.ZipFile(OUT/'ANALYSIS_PACKAGE.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as z:
        for f in files:
            if f.exists():z.write(f,f.name,compress_type=zipfile.ZIP_STORED if f.suffix=='.zip' else zipfile.ZIP_DEFLATED)
        for name in tools:z.write(ROOT/'tools'/name,'tools/'+name)
    print(json.dumps(dict(package=str(OUT/'ANALYSIS_PACKAGE.zip'),bytes=(OUT/'ANALYSIS_PACKAGE.zip').stat().st_size)))

if __name__=='__main__':main()
