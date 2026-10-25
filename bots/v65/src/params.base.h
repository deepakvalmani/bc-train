#pragma once
// Tunables. tools/variant.py rewrites these lines to make sweep copies.
constexpr bool   TRACE        = false;
constexpr int    BANK_AT      = 30;     // carried gems before a dedicated trip
constexpr int    BANK_NEAR    = 5;      // bank any gems if an altar is this close
constexpr float  RECALL_HP    = 0.38;  // recall below this fraction
constexpr float  CLAIMED_MULT = 0.35f;  // score mult for solo groups another ally claimed
constexpr float  STICKY_MULT  = 1.5;  // hysteresis for current target
constexpr float  JOIN_MULT    = 2.0;   // score mult for team targets an ally already claimed
constexpr double SOLO_SOAK    = 0.0;    // solo a camp if expected damage <= this * current HP
constexpr double TEAM_SOAK    = 0.5;    // team job allowed if damage <= this * team HP
constexpr double GEM_W        = 1.8;
constexpr double GOLD_W       = 0.8;
// Draft preference (champion_draft ids): ryth0 vesper1 vendetta2 cassi_issac3 stellar4
// prism5 marcella6 willow7 ren8 varg9 tavi10. Must list all 11.
constexpr int    DRAFT_ORDER[] = {3,4,10,9,0,2,7,6,1,8,5};
// ---- v2 ----
constexpr bool   SQUAD          = true;   // size squads per camp instead of deathball/solo split
constexpr double SQUAD_SOAK     = 0.36;    // front-liner may lose this fraction of avg HP per fight
constexpr float  OVERSTAFF_MULT = 0.097;   // score mult for groups already fully staffed by allies
constexpr bool   USE_AOE        = true;   // cast ground-target area spells on camps
constexpr bool   USE_CC         = true;   // cast pure stuns on hitting camps
constexpr bool   USE_SHIELD     = true;   // self-shield when hurt
constexpr bool   STRAY_HITS     = true;   // v1 behaviour: hit any camp in reach
// ---- v3 ----
constexpr bool   RETREAT        = true;   // step out of danger before recalling
constexpr bool   TRACK_HP       = true;   // score camps by remaining (persistent) health
// ---- v4 ----
constexpr float  STUN_FIRST_STR = 60.0;  // camps hitting at least this hard get stunned before nuked
constexpr bool   AOE_PVP        = true;   // cast area-damage spells on enemy champions in fights
constexpr int    SHOP_GOLD      = 90;      // recall to shop at this much gold (0 = off)
constexpr bool   GROWTH_SCALE   = true;   // scale squad maths by our shard growth
constexpr double MONO_BIAS      = 1.0;    // score multiplier for monolith groups
// ---- v6 ----
constexpr bool   FIX_WAIT          = true;  // no join/sticky bonus for respawning camps
constexpr float  WAIT_CLAIMED_MULT = 0.1;  // score mult for respawning camps an ally already waits on
// ---- v8 ----
constexpr bool   SMART_PVP      = true;   // spells on enemies, weakest target, flee when outnumbered
// ---- v11 ----
constexpr bool   OWN_LOCKS        = true;  // carry an altar lock and drop it on altars we use
constexpr int    LOCKED_DETOUR    = 10;    // prefer a free altar unless it is this much farther
constexpr int    BANK_STUCK_TURNS = 11;     // no banking progress for this long -> farm instead
constexpr int    BANK_RETRY_WAIT  = 25;    // ...for this many rounds, then retry
// ---- v12 ----
constexpr bool   GEM_HUNT       = false;   // chase/prioritise enemies carrying many gems
constexpr int    HUNT_MIN_GEMS  = 10;
constexpr int    HUNT_RANGE     = 3;  // was 7: long hunts never caught same-speed carriers
constexpr bool   LOCK_SNIPE     = true;   // drop a lock on an altar an enemy is tributing at
constexpr bool   CONTEST        = false;   // step onto regions enemies are capturing
constexpr bool   TELEPORT       = false;   // bank at walled-in altars via teleport crystal
constexpr int    PRIVATE_SLACK  = 10;     // accept a private-altar trip this much longer
constexpr bool   PATH_DIST      = false;   // score camps by walking distance, skip unreachable
constexpr bool   DRAFT_MEMORY   = true;   // draft writes spawn->group walking distances
constexpr bool   DRAFT_BY_SIZE  = false;   // separate draft order for 5-champion maps
constexpr int    DRAFT_ORDER5[] = {2,4,9,10,3,7,0,6,1,8,5};
constexpr bool   WARDS          = true;   // keep a ward on our target camp
// ---- v17: upgrades ----
constexpr bool   MIMIC_SHOP        = true;   // copy the top-20 ladder shop (see buy_items)
constexpr bool   SMART_SHOP         = true;   // role-based shard mix
constexpr bool   HOME_FIRST         = true;   // first emblem = Home (recall 5 -> 3 turns)
constexpr double CASTER_FOCUS_SHARE = 0.4;    // Stellar/Tavi/Cassi/Prism: share of shards in Focus
constexpr double TANK_HEALTH_SHARE  = 0.3;    // Ryth/Varg/Marcella: share of shards in Health
constexpr bool   TAVI_FIELD_SHOP    = true;   // Tavi buys shards anywhere
// ---- v17: team fighting ----
constexpr bool   TEAMFIGHT      = true;   // shared engage signal + marked target + stuns first + stunner priority
constexpr int    ENGAGE_TTL     = 3;      // rounds an engage call stays active
constexpr int    JOIN_RANGE     = 8;      // answer engage calls within this distance
// ---- v17: gem safety ----
constexpr bool   GEM_SAFETY     = true;   // protect carried gems
constexpr int    SAFE_GEMS      = 15;     // with this many gems, avoid even fights (back off instead)
constexpr int    BANK_AT_DANGER = 10;     // bank threshold while enemies are around
constexpr int    DANGER_MEMORY  = 20;     // rounds an enemy sighting keeps us cautious
// ---- v17: monolith late-game ----
constexpr bool   MONOLITH        = true;   // allow whole-team monolith sieges late
constexpr int    MONO_MIN_ROUND  = 120;
constexpr double MONO_MIN_GROWTH = 1.2;   // our Strength must be at least 2x base
constexpr double TEAM_SOAK_MONO  = 3.0;   // damage budget in team-HP units (rotations heal at spawn)
// ---- v17: map-aware draft ----
constexpr bool   MAP_DRAFT      = true;   // choose picks from the map's camps, size and enemy picks
constexpr bool   COUNTER_STUN   = true;   // Marcella (stun immune) last if the enemy stacks stuns
// ---- v17: corners fixes (from the hello/Univardisty replays) ----
constexpr bool   FLEE_OUTNUMBERED = false;  // retreat when outnumbered at any HP
constexpr bool   DANGER_SQUADS    = true;  // camps near recent enemy sightings need >= 2 champions
// ---- v18: fight back (hello/Univardisty killed us 14:0 and 8:0) ----
constexpr bool   KITE             = true;  // fire spells/attacks at enemies in reach before retreating
constexpr bool   CHASE            = false;  // step into range of the PvP target instead of returning to camps
// ---- v19: remaining mechanics ----
constexpr bool   EMBLEM_PLAN      = true;  // after Home: Durability, then Jungle/Treasure/Monster by role
constexpr int    EMBLEM_COUNT     = 2;     // role emblems to finish before Power shards
constexpr bool   TAVI_SELL        = true;  // Tavi sells Power shards on spawn to finish an emblem
constexpr bool   PVP_RESET        = true;  // attack, reset, attack again on enemy champions
constexpr bool   SECURE_KILLS     = true;  // enemies we can kill this turn come first; never flee from them
constexpr bool   CHAMP_AWARE      = true;  // Cassi/Issac linked bags, avoid Ren when low, spread vs Ryth
constexpr bool   BUSH_AMBUSH      = true;  // wait for respawns in bushes; retreat into bushes
constexpr bool   WARD_SCOUT       = false;  // ward the enemies' approach once we see the camp ourselves
constexpr bool   HEATMAP          = true;  // long-term map of where enemies walk
constexpr float  HEAT_DANGER      = 3.0;  // heat at which a camp needs >= 2 champions
// ---- v20: time-budget fixes (trace: dead 0-21%, recall 3-30% of champion turns) ----
constexpr bool   WALK_HOME        = true;  // walk to spawn instead of recalling when it is as close
constexpr bool   RETREAT_HOME     = true;  // retreat steps lean towards our spawn
constexpr double RECALL_HP_DANGER = 0.0;   // recall threshold near enemies (0.55 tested worse: gives up fights)
constexpr bool   SAFE_RECALL      = true;  // never start a recall within reach of an awake camp/enemy
constexpr bool   LINKED_CARE      = true;  // Cassi (linked to Issac) leaves fights earlier
constexpr double CASSI_RECALL_HP  = 0.55;
constexpr bool   KITE_STEP        = false; // no-op: ranged champions cannot move after attacking
constexpr bool   CHOICE_CACHE     = true;  // reuse the camp choice while calmly walking (fuel)
constexpr int    CHOICE_TTL       = 3;
constexpr bool   PRUNE_CAMPS      = true;  // skip camps whose best-case score cannot win (fuel)
constexpr bool   STATE_FROM_SNAPSHOT = true; // skip camp_group::state() for groups with live monsters in view
constexpr bool   LOCAL_BITS       = true;  // export visibility once per turn, test bits locally (fuel)
constexpr bool   FUEL_GUARD       = true;  // stop scoring camps when fuel runs low
constexpr int    FUEL_RESERVE     = 40000;
// ---- v22: fuel + navigation ----
constexpr bool   STATIC_NAV       = false; // cached per-destination distance fields (altars, camps)
constexpr int    NAV_BUILD_FUEL   = 80000; // build a new field only with this much fuel left (start-of-turn builds)
constexpr bool   ADAPTIVE_BANK    = true;  // bank threshold = BANK_K * sqrt(distance to altar)
constexpr double BANK_K           = 5.0;
constexpr int    BANK_MIN         = 8;
constexpr int    BANK_MAX         = 55;
// ---- v23: economy ----
constexpr bool   ZONE_FARM        = false; // camp score includes the walk to bank its gems
constexpr double ZONE_W           = 1.0;
constexpr bool   SPLIT_CAPTURE    = false; // leave a dead camp an ally is already capturing
constexpr bool   PER_ALTAR_RETRY  = true;  // stuck at one altar -> avoid it, retry others (not a 25-round give-up)
// ---- v26: from 15 ladder games vs the top 3 (133 deaths; 23-42% of turns dead) ----
constexpr bool   NO_CASSI         = false; // draft Cassi/Issac last (linked deaths: 37 of them)
constexpr bool   CAREFUL_PVP      = true;  // count enemies within 8; squishies chase only for kills; no chase/join/contest outnumbered
constexpr bool   BURST_EXIT       = true;  // lost >= BURST_FRAC of max HP since last turn -> disengage
constexpr float  BURST_FRAC       = 0.3;
constexpr bool   NAV_BIG          = false; // cached distance fields on big maps only (walk turns overflowed fuel)
constexpr int    NAV_BIG_AREA     = 2600;  // lanes 90x30, corners 71x71, expanse 80x80
constexpr bool   DEAD_CAMP_LEAVE  = true;  // leave a dead camp whose capture tiles are all occupied by allies
// ---- v29: from Univardisty's per-champion ladder stats + corners replay ----
constexpr bool   UNIV_SHOP        = true;  // Durability(Health) emblem first (Tavi +Treasure Focus), then Power shards of main stat; no Home
constexpr int    SHOP_STYLE       = 3;     // with UNIV_SHOP: 1 = Univardisty (Durability Health, Power main stat), 2 = Quantom (Monster Str, Durability Health, Power Str+Health), 3 = procless (Durability+Jungle main stat, Bruiser Health, Power Str)
constexpr bool   CENTRE_REGROUP   = false; // centre camps (equidistant from spawns) only as a gathered squad
constexpr int    CENTRE_MARGIN    = 2;     // |d(ours) - d(theirs)| <= this -> centre camp
constexpr int    REGROUP_SIZE     = 3;
constexpr int    REGROUP_DIST     = 8;     // wait this far out (camp range 3, enemy burst range ~4)
constexpr int    REGROUP_MAX      = 15;    // ...for at most this many turns
constexpr int    CHASE_MAX        = 2;     // consecutive chase turns before giving up
constexpr bool   TOP_DRAFT        = true;  // per-map winning drafts from 233 top-13 ladder games
// ---- v36: basics (ladder: 125 games, 59-66; solo farming) ----
constexpr bool   FINISH_MODE      = true;  // bank everything once banked + team carried >= winning gems
constexpr int    FINISH_SLACK     = 15;    // start slightly early (allies' bags are estimates)
// ---- v37: decision gap vs Mite (we die 18-37% of the time, they 0-4%; they take 0-4k champion damage, we 3-10k) ----
constexpr bool   JOIN_FIGHT         = false; // never walk to a marked enemy (walks into their burst range)
constexpr bool   AVOID_ENEMY_CAMPS  = false;  // skip camps with a visible enemy champion nearby
constexpr int    ENEMY_CAMP_RADIUS  = 7;
constexpr bool   COLLECTOR_FOCUS    = true;  // casters buy Focus (Mite: Cassi 520, Stellar 330 at r300)
constexpr bool   COLLECTORS         = false;  // melee leave captures to nearby ranged allies
constexpr int    COLLECTOR_RADIUS   = 8;
// ---- v39: who goes to the contested middle (Mite corners r20: tank trio together; ours: squishies alone) ----
constexpr bool   TANK_CENTRE        = true;
constexpr float  TANK_HP            = 1000.0f;  // Varg, Ryth, Marcella (base) count as tanks
constexpr double SQUISHY_CENTRE_MULT = 0.15;    // a squishy champion without a tank nearby avoids centre camps
constexpr double TANK_CENTRE_MULT   = 1.5;      // tanks are drawn to them
// ---- v40: Cassi/Issac survival (they were 45% dead on interlock; half of all our deaths; linked fate) ----
constexpr bool   LINKED_PAIR      = false;   // recall when the weaker of Cassi/Issac is low (visible partner)
constexpr float  PAIR_RECALL_HP   = 0.3877;
constexpr bool   CASSI_KEEP_RANGE = false;   // Cassi backs off when an enemy is within 3, or within 6 with <=1 ally near

// Additional exposed strategy decisions for broad local training.
constexpr int RETREAT_DISTANCE_W = 10;
constexpr int RETREAT_HOME_W = 3;
constexpr int RETREAT_BUSH_BONUS = 15;
constexpr int RETREAT_SPREAD_PENALTY = 8;
constexpr float BURST_FOCUS_MULT = 1.5;
constexpr float TARGET_HP_W = 1.0;
constexpr float TARGET_GEM_W = 20.0;
constexpr float MARK_PRIORITY = 1000000.0;
constexpr float KILL_PRIORITY = 2000000.0;
constexpr float REN_AVOID_HP = 0.4;
constexpr int REN_TARGET_PENALTY = 500;
constexpr float EQUAL_FIGHT_HP = 0.6;
// v48: Lanchester square-law fight estimate (hp x dps of visible allies vs visible foes). Off by default; the trainer enables it per map.
constexpr bool  LANCH_ON = false;         // leave a fight whose power ratio is below LANCH_MIN
constexpr bool  LANCH_GATE = false;       // do not start a camp walk-in when enemies near it out-power us
constexpr float LANCH_MIN = 0.8;
constexpr float LANCH_FOCUS_W = 0.2;      // spell damage per round, as a share of Focus
constexpr int   LANCH_SKIP = 8;           // rounds to skip a camp the gate rejected
constexpr float LANCH_RECALL_HP = 0.0;    // >0: recall at this HP share when the ratio is bad (0 = off)
constexpr int   LANCH_CAMP_R = 7;         // enemies this close to the camp count for the gate
constexpr float HUNT_HP = 0.5;
constexpr int   DANGER_STR = 0;     // camps at least this strong (bosses, 200 Strength / 20000 HP) are walled off for pathing and never fought by accident
constexpr int   DANGER_R = 5;
constexpr bool  DANGER_BLOCK = false;   // path around boss camps (cost fuel, froze fracture); the stray-fight filter stays on
constexpr bool  HOME_FIRST_MIMIC = true;   // Home emblem (3-turn recall) is the first emblem in the mimic shop
constexpr bool  DASH_ESCAPE = true;
constexpr float DASH_ESCAPE_HP = 0.4f;   // dash out of reach below this HP share when a dash is ready
constexpr float CAMP_ENTER_HP = 0.65;   // below this HP share do not start walking into a camp: recall and heal first
constexpr float CONTEST_HP = 0.5;
constexpr float CHASE_HP = 0.5;
constexpr float JOIN_HP = 0.5;
constexpr float ALLY_HEAL_HP = 0.6;
constexpr float SPAWN_HEAL_HP = 1.0; // wait on spawn until turn-end recovery when below this fraction
constexpr float SELF_SHIELD_HP = 0.9885;
constexpr int PVP_FOE_RADIUS = 8;
constexpr int PVP_NORMAL_RADIUS = 5;
constexpr int PVP_ALLY_RADIUS = 5;
constexpr float CHASE_TANK_HP = 900.0;
constexpr int CASSI_DANGER_NEAR = 3;
constexpr int CASSI_DANGER_FAR = 6;
constexpr int ESCORT_RADIUS = 8;
constexpr int DANGER_CAMP_RADIUS = 7;
constexpr int HEAT_DECAY_TURNS = 10;
constexpr float HEAT_DECAY = 0.9;
constexpr float HEAT_ADD = 0.9975;
constexpr float CAMP_OVERHEAD = 5.0;
constexpr float ZONE_BAG = 30.0;
constexpr int MONO_DAMAGE_MIN = 200;
constexpr int BANK_NO_GAIN = 30;
constexpr int ENDGAME_ROUTE_MULT = 2;
constexpr int ENDGAME_SLACK = 25;
constexpr float ALLY_BAG_ESTIMATE = 1.0;
constexpr int CAPTURE_SKIP_TURNS = 8;
constexpr int DEAD_SKIP_TURNS = 6;
constexpr int SQUAD_READY_RADIUS = 4;
constexpr int CHOICE_FAR_DISTANCE = 6;
constexpr int SHOP_MAX_GEMS = 10;
constexpr int SHOP_THREAT_RADIUS = 5;
constexpr int PATH_BUILD_FUEL = 70000;
constexpr bool CUSTOM_SHOP = true;
constexpr int TANK_ITEM_FAMILY1 = 2;
constexpr int TANK_ITEM_STAT1 = 0;
constexpr int TANK_ITEM_FAMILY2 = 4;
constexpr int TANK_ITEM_STAT2 = 0;
constexpr int TANK_ITEM_FAMILY3 = 6;
constexpr int TANK_ITEM_STAT3 = 2;
constexpr int TANK_POWER_STAT = 0;
constexpr int CASTER_ITEM_FAMILY1 = 2;
constexpr int CASTER_ITEM_STAT1 = 1;
constexpr int CASTER_ITEM_FAMILY2 = 4;
constexpr int CASTER_ITEM_STAT2 = 1;
constexpr int CASTER_ITEM_FAMILY3 = 6;
constexpr int CASTER_ITEM_STAT3 = 2;
constexpr int CASTER_POWER_STAT = 1;
constexpr int MELEE_ITEM_FAMILY1 = 2;
constexpr int MELEE_ITEM_STAT1 = 0;
constexpr int MELEE_ITEM_FAMILY2 = 4;
constexpr int MELEE_ITEM_STAT2 = 0;
constexpr int MELEE_ITEM_FAMILY3 = 4;
constexpr int MELEE_ITEM_STAT3 = 2;
constexpr int MELEE_POWER_STAT = 0;
constexpr int CUSTOM_EMBLEM_COUNT = 3;
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
constexpr bool DEATH_MEMORY_ON = true;
constexpr int  DEATH_RADIUS    = 8;     // avoid camps this close to a recent death site
constexpr int  DEATH_TTL       = 150;   // rounds

// ---- v45 team play ----
constexpr int   RALLY_FOES  = 2;    // foes near a champion before it calls allies
constexpr float RALLY_HP    = 0.5f; // allies answer only when this healthy
constexpr int   RALLY_RANGE = 14;   // answer calls within this distance
constexpr bool   STICKY_BANK      = true;  // keep walking to the altar once a bank trip started
constexpr bool   BANK_BLOCK_CAMPS = true;  // bank walks path around every camp position, seen or not (the-farm: vision flip loop)
