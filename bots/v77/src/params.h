#pragma once
// Tunables. tools/variant.py rewrites these lines to make sweep copies.
// tunable (see tune_gen.h): TRACE = false
// tunable (see tune_gen.h): BANK_AT = 30     // carried gems before a dedicated trip
// tunable (see tune_gen.h): BANK_NEAR = 5      // bank any gems if an altar is this close
// tunable (see tune_gen.h): RECALL_HP = 0.38  // recall below this fraction
// tunable (see tune_gen.h): CLAIMED_MULT = 0.35f  // score mult for solo groups another ally claimed
// tunable (see tune_gen.h): STICKY_MULT = 1.5  // hysteresis for current target
// tunable (see tune_gen.h): JOIN_MULT = 2.0   // score mult for team targets an ally already claimed
// tunable (see tune_gen.h): SOLO_SOAK = 0.0    // solo a camp if expected damage <= this * current HP
// tunable (see tune_gen.h): TEAM_SOAK = 0.5    // team job allowed if damage <= this * team HP
// tunable (see tune_gen.h): GEM_W = 1.8
// tunable (see tune_gen.h): GOLD_W = 0.8
// Draft preference (champion_draft ids): ryth0 vesper1 vendetta2 cassi_issac3 stellar4
// prism5 marcella6 willow7 ren8 varg9 tavi10. Must list all 11.
constexpr int    DRAFT_ORDER[] = {3,4,10,9,0,2,7,6,1,8,5};
// ---- v2 ----
// tunable (see tune_gen.h): SQUAD = true   // size squads per camp instead of deathball/solo split
// tunable (see tune_gen.h): SQUAD_SOAK = 0.36    // front-liner may lose this fraction of avg HP per fight
// tunable (see tune_gen.h): OVERSTAFF_MULT = 0.097   // score mult for groups already fully staffed by allies
// tunable (see tune_gen.h): USE_AOE = true   // cast ground-target area spells on camps
// tunable (see tune_gen.h): USE_CC = true   // cast pure stuns on hitting camps
// tunable (see tune_gen.h): USE_SHIELD = true   // self-shield when hurt
// tunable (see tune_gen.h): STRAY_HITS = true   // v1 behaviour: hit any camp in reach
// ---- v3 ----
// tunable (see tune_gen.h): RETREAT = true   // step out of danger before recalling
// tunable (see tune_gen.h): TRACK_HP = true   // score camps by remaining (persistent) health
// ---- v4 ----
// tunable (see tune_gen.h): STUN_FIRST_STR = 60.0  // camps hitting at least this hard get stunned before nuked
// tunable (see tune_gen.h): AOE_PVP = true   // cast area-damage spells on enemy champions in fights
// tunable (see tune_gen.h): SHOP_GOLD = 90      // recall to shop at this much gold (0 = off)
// tunable (see tune_gen.h): GROWTH_SCALE = true   // scale squad maths by our shard growth
// tunable (see tune_gen.h): MONO_BIAS = 1.0    // score multiplier for monolith groups
// ---- v6 ----
// tunable (see tune_gen.h): FIX_WAIT = true  // no join/sticky bonus for respawning camps
// tunable (see tune_gen.h): WAIT_CLAIMED_MULT = 0.1  // score mult for respawning camps an ally already waits on
// ---- v8 ----
// tunable (see tune_gen.h): SMART_PVP = true   // spells on enemies, weakest target, flee when outnumbered
// ---- v11 ----
// tunable (see tune_gen.h): OWN_LOCKS = true  // carry an altar lock and drop it on altars we use
// tunable (see tune_gen.h): LOCKED_DETOUR = 10    // prefer a free altar unless it is this much farther
// tunable (see tune_gen.h): BANK_STUCK_TURNS = 11     // no banking progress for this long -> farm instead
// tunable (see tune_gen.h): BANK_RETRY_WAIT = 25    // ...for this many rounds, then retry
// ---- v12 ----
// tunable (see tune_gen.h): GEM_HUNT = false   // chase/prioritise enemies carrying many gems
// tunable (see tune_gen.h): HUNT_MIN_GEMS = 10
// tunable (see tune_gen.h): HUNT_RANGE = 3  // was 7: long hunts never caught same-speed carriers
// tunable (see tune_gen.h): LOCK_SNIPE = true   // drop a lock on an altar an enemy is tributing at
// tunable (see tune_gen.h): CONTEST = false   // step onto regions enemies are capturing
// tunable (see tune_gen.h): TELEPORT = false   // bank at walled-in altars via teleport crystal
// tunable (see tune_gen.h): PRIVATE_SLACK = 10     // accept a private-altar trip this much longer
// tunable (see tune_gen.h): PATH_DIST = false   // score camps by walking distance, skip unreachable
constexpr bool   DRAFT_MEMORY   = true;   // draft writes spawn->group walking distances
constexpr bool   DRAFT_BY_SIZE  = false;   // separate draft order for 5-champion maps
constexpr int    DRAFT_ORDER5[] = {2,4,9,10,3,7,0,6,1,8,5};
// tunable (see tune_gen.h): WARDS = true   // keep a ward on our target camp
// ---- v17: upgrades ----
// tunable (see tune_gen.h): MIMIC_SHOP = true   // copy the top-20 ladder shop (see buy_items)
// tunable (see tune_gen.h): SMART_SHOP = true   // role-based shard mix
// tunable (see tune_gen.h): HOME_FIRST = true   // first emblem = Home (recall 5 -> 3 turns)
// tunable (see tune_gen.h): CASTER_FOCUS_SHARE = 0.4    // Stellar/Tavi/Cassi/Prism: share of shards in Focus
// tunable (see tune_gen.h): TANK_HEALTH_SHARE = 0.3    // Ryth/Varg/Marcella: share of shards in Health
// tunable (see tune_gen.h): TAVI_FIELD_SHOP = true   // Tavi buys shards anywhere
// ---- v17: team fighting ----
// tunable (see tune_gen.h): TEAMFIGHT = true   // shared engage signal + marked target + stuns first + stunner priority
// tunable (see tune_gen.h): ENGAGE_TTL = 3      // rounds an engage call stays active
// tunable (see tune_gen.h): JOIN_RANGE = 8      // answer engage calls within this distance
// ---- v17: gem safety ----
// tunable (see tune_gen.h): GEM_SAFETY = true   // protect carried gems
// tunable (see tune_gen.h): SAFE_GEMS = 15     // with this many gems, avoid even fights (back off instead)
// tunable (see tune_gen.h): BANK_AT_DANGER = 10     // bank threshold while enemies are around
// tunable (see tune_gen.h): DANGER_MEMORY = 20     // rounds an enemy sighting keeps us cautious
// ---- v17: monolith late-game ----
// tunable (see tune_gen.h): MONOLITH = true   // allow whole-team monolith sieges late
// tunable (see tune_gen.h): MONO_MIN_ROUND = 120
// tunable (see tune_gen.h): MONO_MIN_GROWTH = 1.2   // our Strength must be at least 2x base
// tunable (see tune_gen.h): TEAM_SOAK_MONO = 3.0   // damage budget in team-HP units (rotations heal at spawn)
// ---- v17: map-aware draft ----
constexpr bool   MAP_DRAFT      = true;   // choose picks from the map's camps, size and enemy picks
constexpr bool   COUNTER_STUN   = true;   // Marcella (stun immune) last if the enemy stacks stuns
// ---- v17: corners fixes (from the hello/Univardisty replays) ----
// tunable (see tune_gen.h): FLEE_OUTNUMBERED = false  // retreat when outnumbered at any HP
// tunable (see tune_gen.h): DANGER_SQUADS = true  // camps near recent enemy sightings need >= 2 champions
// ---- v18: fight back (hello/Univardisty killed us 14:0 and 8:0) ----
// tunable (see tune_gen.h): KITE = true  // fire spells/attacks at enemies in reach before retreating
// tunable (see tune_gen.h): CHASE = false  // step into range of the PvP target instead of returning to camps
// ---- v19: remaining mechanics ----
// tunable (see tune_gen.h): EMBLEM_PLAN = true  // after Home: Durability, then Jungle/Treasure/Monster by role
// tunable (see tune_gen.h): EMBLEM_COUNT = 2     // role emblems to finish before Power shards
// tunable (see tune_gen.h): TAVI_SELL = true  // Tavi sells Power shards on spawn to finish an emblem
// tunable (see tune_gen.h): PVP_RESET = true  // attack, reset, attack again on enemy champions
// tunable (see tune_gen.h): SECURE_KILLS = true  // enemies we can kill this turn come first; never flee from them
// tunable (see tune_gen.h): CHAMP_AWARE = true  // Cassi/Issac linked bags, avoid Ren when low, spread vs Ryth
// tunable (see tune_gen.h): BUSH_AMBUSH = true  // wait for respawns in bushes; retreat into bushes
// tunable (see tune_gen.h): WARD_SCOUT = false  // ward the enemies' approach once we see the camp ourselves
// tunable (see tune_gen.h): HEATMAP = true  // long-term map of where enemies walk
// tunable (see tune_gen.h): HEAT_DANGER = 3.0  // heat at which a camp needs >= 2 champions
// ---- v20: time-budget fixes (trace: dead 0-21%, recall 3-30% of champion turns) ----
// tunable (see tune_gen.h): WALK_HOME = true  // walk to spawn instead of recalling when it is as close
// tunable (see tune_gen.h): RETREAT_HOME = true  // retreat steps lean towards our spawn
// tunable (see tune_gen.h): RECALL_HP_DANGER = 0.0   // recall threshold near enemies (0.55 tested worse: gives up fights)
// tunable (see tune_gen.h): SAFE_RECALL = true  // never start a recall within reach of an awake camp/enemy
// tunable (see tune_gen.h): LINKED_CARE = true  // Cassi (linked to Issac) leaves fights earlier
// tunable (see tune_gen.h): CASSI_RECALL_HP = 0.55
// tunable (see tune_gen.h): KITE_STEP = false // no-op: ranged champions cannot move after attacking
// tunable (see tune_gen.h): CHOICE_CACHE = true  // reuse the camp choice while calmly walking (fuel)
// tunable (see tune_gen.h): CHOICE_TTL = 3
// tunable (see tune_gen.h): PRUNE_CAMPS = true  // skip camps whose best-case score cannot win (fuel)
// tunable (see tune_gen.h): STATE_FROM_SNAPSHOT = true // skip camp_group::state() for groups with live monsters in view
// tunable (see tune_gen.h): LOCAL_BITS = true  // export visibility once per turn, test bits locally (fuel)
// tunable (see tune_gen.h): FUEL_GUARD = true  // stop scoring camps when fuel runs low
// tunable (see tune_gen.h): FUEL_RESERVE = 40000
// ---- v22: fuel + navigation ----
// tunable (see tune_gen.h): STATIC_NAV = false // cached per-destination distance fields (altars, camps)
// tunable (see tune_gen.h): NAV_BUILD_FUEL = 80000 // build a new field only with this much fuel left (start-of-turn builds)
// tunable (see tune_gen.h): ADAPTIVE_BANK = true  // bank threshold = BANK_K * sqrt(distance to altar)
// tunable (see tune_gen.h): BANK_K = 5.0
// tunable (see tune_gen.h): BANK_MIN = 8
// tunable (see tune_gen.h): BANK_MAX = 55
// ---- v23: economy ----
// tunable (see tune_gen.h): ZONE_FARM = false // camp score includes the walk to bank its gems
// tunable (see tune_gen.h): ZONE_W = 1.0
// tunable (see tune_gen.h): SPLIT_CAPTURE = false // leave a dead camp an ally is already capturing
// tunable (see tune_gen.h): PER_ALTAR_RETRY = true  // stuck at one altar -> avoid it, retry others (not a 25-round give-up)
// ---- v26: from 15 ladder games vs the top 3 (133 deaths; 23-42% of turns dead) ----
constexpr bool   NO_CASSI         = false; // draft Cassi/Issac last (linked deaths: 37 of them)
// tunable (see tune_gen.h): CAREFUL_PVP = true  // count enemies within 8; squishies chase only for kills; no chase/join/contest outnumbered
// tunable (see tune_gen.h): BURST_EXIT = true  // lost >= BURST_FRAC of max HP since last turn -> disengage
// tunable (see tune_gen.h): BURST_FRAC = 0.3
// tunable (see tune_gen.h): NAV_BIG = false // cached distance fields on big maps only (walk turns overflowed fuel)
// tunable (see tune_gen.h): NAV_BIG_AREA = 2600  // lanes 90x30, corners 71x71, expanse 80x80
// tunable (see tune_gen.h): DEAD_CAMP_LEAVE = true  // leave a dead camp whose capture tiles are all occupied by allies
// ---- v29: from Univardisty's per-champion ladder stats + corners replay ----
// tunable (see tune_gen.h): UNIV_SHOP = true  // Durability(Health) emblem first (Tavi +Treasure Focus), then Power shards of main stat; no Home
// tunable (see tune_gen.h): SHOP_STYLE = 3     // with UNIV_SHOP: 1 = Univardisty (Durability Health, Power main stat), 2 = Quantom (Monster Str, Durability Health, Power Str+Health), 3 = procless (Durability+Jungle main stat, Bruiser Health, Power Str)
// tunable (see tune_gen.h): CENTRE_REGROUP = false // centre camps (equidistant from spawns) only as a gathered squad
// tunable (see tune_gen.h): CENTRE_MARGIN = 2     // |d(ours) - d(theirs)| <= this -> centre camp
// tunable (see tune_gen.h): REGROUP_SIZE = 3
// tunable (see tune_gen.h): REGROUP_DIST = 8     // wait this far out (camp range 3, enemy burst range ~4)
// tunable (see tune_gen.h): REGROUP_MAX = 15    // ...for at most this many turns
// tunable (see tune_gen.h): CHASE_MAX = 2     // consecutive chase turns before giving up
constexpr bool   TOP_DRAFT        = true;  // per-map winning drafts from 233 top-13 ladder games
// ---- v36: basics (ladder: 125 games, 59-66; solo farming) ----
// tunable (see tune_gen.h): FINISH_MODE = true  // bank everything once banked + team carried >= winning gems
// tunable (see tune_gen.h): FINISH_SLACK = 15    // start slightly early (allies' bags are estimates)
// ---- v37: decision gap vs Mite (we die 18-37% of the time, they 0-4%; they take 0-4k champion damage, we 3-10k) ----
// tunable (see tune_gen.h): JOIN_FIGHT = false // never walk to a marked enemy (walks into their burst range)
// tunable (see tune_gen.h): AVOID_ENEMY_CAMPS = false  // skip camps with a visible enemy champion nearby
// tunable (see tune_gen.h): ENEMY_CAMP_RADIUS = 7
// tunable (see tune_gen.h): COLLECTOR_FOCUS = true  // casters buy Focus (Mite: Cassi 520, Stellar 330 at r300)
// tunable (see tune_gen.h): COLLECTORS = false  // melee leave captures to nearby ranged allies
// tunable (see tune_gen.h): COLLECTOR_RADIUS = 8
// ---- v39: who goes to the contested middle (Mite corners r20: tank trio together; ours: squishies alone) ----
// tunable (see tune_gen.h): TANK_CENTRE = true
// tunable (see tune_gen.h): TANK_HP = 1000.0f  // Varg, Ryth, Marcella (base) count as tanks
// tunable (see tune_gen.h): SQUISHY_CENTRE_MULT = 0.15    // a squishy champion without a tank nearby avoids centre camps
// tunable (see tune_gen.h): TANK_CENTRE_MULT = 1.5      // tanks are drawn to them
// ---- v40: Cassi/Issac survival (they were 45% dead on interlock; half of all our deaths; linked fate) ----
// tunable (see tune_gen.h): LINKED_PAIR = false   // recall when the weaker of Cassi/Issac is low (visible partner)
// tunable (see tune_gen.h): PAIR_RECALL_HP = 0.3877
// tunable (see tune_gen.h): CASSI_KEEP_RANGE = false   // Cassi backs off when an enemy is within 3, or within 6 with <=1 ally near

// Additional exposed strategy decisions for broad local training.
// tunable (see tune_gen.h): RETREAT_DISTANCE_W = 10
// tunable (see tune_gen.h): RETREAT_HOME_W = 3
// tunable (see tune_gen.h): RETREAT_BUSH_BONUS = 15
// tunable (see tune_gen.h): RETREAT_SPREAD_PENALTY = 8
// tunable (see tune_gen.h): BURST_FOCUS_MULT = 1.5
// tunable (see tune_gen.h): TARGET_HP_W = 1.0
// tunable (see tune_gen.h): TARGET_GEM_W = 20.0
// tunable (see tune_gen.h): MARK_PRIORITY = 1000000.0
// tunable (see tune_gen.h): KILL_PRIORITY = 2000000.0
// tunable (see tune_gen.h): REN_AVOID_HP = 0.4
// tunable (see tune_gen.h): REN_TARGET_PENALTY = 500
// tunable (see tune_gen.h): EQUAL_FIGHT_HP = 0.6
// v48: Lanchester square-law fight estimate (hp x dps of visible allies vs visible foes). Off by default; the trainer enables it per map.
// tunable (see tune_gen.h): LANCH_ON = false         // leave a fight whose power ratio is below LANCH_MIN
// tunable (see tune_gen.h): LANCH_GATE = false       // do not start a camp walk-in when enemies near it out-power us
// tunable (see tune_gen.h): LANCH_MIN = 0.8
// tunable (see tune_gen.h): LANCH_FOCUS_W = 0.2      // spell damage per round, as a share of Focus
// tunable (see tune_gen.h): LANCH_SKIP = 8           // rounds to skip a camp the gate rejected
// tunable (see tune_gen.h): LANCH_RECALL_HP = 0.0    // >0: recall at this HP share when the ratio is bad (0 = off)
// tunable (see tune_gen.h): LANCH_CAMP_R = 7         // enemies this close to the camp count for the gate
// tunable (see tune_gen.h): HUNT_HP = 0.5
// tunable (see tune_gen.h): DANGER_STR = 0     // camps at least this strong (bosses, 200 Strength / 20000 HP) are walled off for pathing and never fought by accident
// tunable (see tune_gen.h): DANGER_R = 5
// tunable (see tune_gen.h): DANGER_BLOCK = false   // path around boss camps (cost fuel, froze fracture); the stray-fight filter stays on
// tunable (see tune_gen.h): HOME_FIRST_MIMIC = true   // Home emblem (3-turn recall) is the first emblem in the mimic shop
// tunable (see tune_gen.h): DASH_ESCAPE = true
// tunable (see tune_gen.h): DASH_ESCAPE_HP = 0.4f   // dash out of reach below this HP share when a dash is ready
// tunable (see tune_gen.h): CAMP_ENTER_HP = 0.65   // below this HP share do not start walking into a camp: recall and heal first
// tunable (see tune_gen.h): CONTEST_HP = 0.5
// tunable (see tune_gen.h): CHASE_HP = 0.5
// tunable (see tune_gen.h): JOIN_HP = 0.5
// tunable (see tune_gen.h): ALLY_HEAL_HP = 0.6
// tunable (see tune_gen.h): SPAWN_HEAL_HP = 1.0 // wait on spawn until turn-end recovery when below this fraction
// tunable (see tune_gen.h): SELF_SHIELD_HP = 0.9885
// tunable (see tune_gen.h): PVP_FOE_RADIUS = 8
// tunable (see tune_gen.h): PVP_NORMAL_RADIUS = 5
// tunable (see tune_gen.h): PVP_ALLY_RADIUS = 5
// tunable (see tune_gen.h): CHASE_TANK_HP = 900.0
// tunable (see tune_gen.h): CASSI_DANGER_NEAR = 3
// tunable (see tune_gen.h): CASSI_DANGER_FAR = 6
// tunable (see tune_gen.h): ESCORT_RADIUS = 8
// tunable (see tune_gen.h): DANGER_CAMP_RADIUS = 7
// tunable (see tune_gen.h): HEAT_DECAY_TURNS = 10
// tunable (see tune_gen.h): HEAT_DECAY = 0.9
// tunable (see tune_gen.h): HEAT_ADD = 0.9975
// tunable (see tune_gen.h): CAMP_OVERHEAD = 5.0
// tunable (see tune_gen.h): ZONE_BAG = 30.0
// tunable (see tune_gen.h): MONO_DAMAGE_MIN = 200
// tunable (see tune_gen.h): BANK_NO_GAIN = 30
// tunable (see tune_gen.h): ENDGAME_ROUTE_MULT = 2
// tunable (see tune_gen.h): ENDGAME_SLACK = 25
// tunable (see tune_gen.h): ALLY_BAG_ESTIMATE = 1.0
// tunable (see tune_gen.h): CAPTURE_SKIP_TURNS = 8
// tunable (see tune_gen.h): DEAD_SKIP_TURNS = 6
// tunable (see tune_gen.h): SQUAD_READY_RADIUS = 4
// tunable (see tune_gen.h): CHOICE_FAR_DISTANCE = 6
// tunable (see tune_gen.h): SHOP_MAX_GEMS = 10
// tunable (see tune_gen.h): SHOP_THREAT_RADIUS = 5
// tunable (see tune_gen.h): PATH_BUILD_FUEL = 70000
// tunable (see tune_gen.h): CUSTOM_SHOP = true
// tunable (see tune_gen.h): TANK_ITEM_FAMILY1 = 2
// tunable (see tune_gen.h): TANK_ITEM_STAT1 = 0
// tunable (see tune_gen.h): TANK_ITEM_FAMILY2 = 4
// tunable (see tune_gen.h): TANK_ITEM_STAT2 = 0
// tunable (see tune_gen.h): TANK_ITEM_FAMILY3 = 6
// tunable (see tune_gen.h): TANK_ITEM_STAT3 = 2
// tunable (see tune_gen.h): TANK_POWER_STAT = 0
// tunable (see tune_gen.h): CASTER_ITEM_FAMILY1 = 2
// tunable (see tune_gen.h): CASTER_ITEM_STAT1 = 1
// tunable (see tune_gen.h): CASTER_ITEM_FAMILY2 = 4
// tunable (see tune_gen.h): CASTER_ITEM_STAT2 = 1
// tunable (see tune_gen.h): CASTER_ITEM_FAMILY3 = 6
// tunable (see tune_gen.h): CASTER_ITEM_STAT3 = 2
// tunable (see tune_gen.h): CASTER_POWER_STAT = 1
// tunable (see tune_gen.h): MELEE_ITEM_FAMILY1 = 2
// tunable (see tune_gen.h): MELEE_ITEM_STAT1 = 0
// tunable (see tune_gen.h): MELEE_ITEM_FAMILY2 = 4
// tunable (see tune_gen.h): MELEE_ITEM_STAT2 = 0
// tunable (see tune_gen.h): MELEE_ITEM_FAMILY3 = 4
// tunable (see tune_gen.h): MELEE_ITEM_STAT3 = 2
// tunable (see tune_gen.h): MELEE_POWER_STAT = 0
// tunable (see tune_gen.h): CUSTOM_EMBLEM_COUNT = 3
constexpr int DRAFT_OPEN_COUNT = 3;
constexpr int DRAFT_MAP_COUNT = 2;
constexpr float DRAFT_SPLASH_RATIO = 0.4;
constexpr int DRAFT_SMALL_AREA = 1700;
constexpr int DRAFT_STUN_COUNT = 3;
constexpr int DRAFT_LARGE_SIZE = 5;
constexpr int DRAFT_EXPANSE[] = {3,9,2,4,10,0,7,6,1,8,5};
constexpr int DRAFT_ROWS[] = {3,9,2,7,4,10,0,6,1,8,5};
constexpr int DRAFT_LANES[] = {3,8,4,10,9,0,2,7,6,1,5};
constexpr int DRAFT_OPENER[] = {3,4,10,9,0,2,7,6,1,8,5};
constexpr int DRAFT_SPLASH[] = {9,0,3,4,10,2,7,6,1,8,5};
constexpr int DRAFT_SMALL[] = {0,9,3,4,10,2,7,6,1,8,5};
constexpr int DRAFT_LARGE[] = {9,2,3,4,10,0,7,6,1,8,5};

constexpr int DRAFT_CORNERS[] = {9,0,4,3,10,2,7,6,1,8,5};

// ---- death memory (25 games vs the top 5: we die 15x/game vs their 1.2; contest: 131 deaths walking into the same ball) ----
// tunable (see tune_gen.h): DEATH_MEMORY_ON = true
// tunable (see tune_gen.h): DEATH_RADIUS = 8     // avoid camps this close to a recent death site
// tunable (see tune_gen.h): DEATH_TTL = 150   // rounds

// ---- v45 team play ----
// tunable (see tune_gen.h): RALLY_FOES = 2    // foes near a champion before it calls allies
// tunable (see tune_gen.h): RALLY_HP = 0.5f // allies answer only when this healthy
// tunable (see tune_gen.h): RALLY_RANGE = 14   // answer calls within this distance
// tunable (see tune_gen.h): STICKY_BANK = true  // keep walking to the altar once a bank trip started
// tunable (see tune_gen.h): BANK_BLOCK_CAMPS = true  // bank walks path around every camp position, seen or not (the-farm: vision flip loop)

// ---- spawn defence (22 Oct: 77% of early deaths are PvP, 5-6 enemies vs our 3-5 in the open at round ~45) ----
// tunable (see tune_gen.h): SPAWN_DEF = true
// tunable (see tune_gen.h): SPAWN_DEF_FOES = 3     // enemy champions within SPAWN_DEF_SEE that trigger the fall-back
// tunable (see tune_gen.h): SPAWN_DEF_SEE = 9
// tunable (see tune_gen.h): SPAWN_DEF_SLACK = 1    // ... when foes > friends - slack (friends = us + allies within 6)
// tunable (see tune_gen.h): SPAWN_DEF_R = 14       // only when we are this close to our spawn
// tunable (see tune_gen.h): SPAWN_DEF_HOLD = 4     // rounds to keep holding after the trigger
#include "tune_gen.h"
