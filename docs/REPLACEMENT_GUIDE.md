> v5 update: rocks/stones are now DROPPED by default (Cameo rock1-7 render
> with a broken palette on the RA temperate theater -- stock Cameo temperate maps
> avoid them). To bring rocks back, uncomment the rock block in ACTOR_OVERRIDES at
> the top of cameo_map_converter.py, or point them at a Cameo actor you have
> verified looks right in the editor.

# CA -> Cameo decoration replacement guide

How the converter handles every Combined-Arms decoration that Cameo does not
have. Two outcomes: REMAPPED to a same-footprint Cameo actor (kept, just a
different sprite), or DROPPED (no same-object match at the same footprint).

To change any choice, edit ACTOR_OVERRIDES at the top of cameo_map_converter.py:
  "ca_actor": "cameo_actor"   remap to a Cameo actor
  "ca_actor": "drop"          remove it
Delete an entry to fall back to the default (drop if Cameo lacks it).


## Remapped automatically (76 types) -- same footprint, same object

| CA actor | -> Cameo | placements |
|---|---|---|
| stones1 | rock1 | 150 |
| stones3 | rock1 | 143 |
| stones2 | rock1 | 142 |
| stones12 | rock1 | 121 |
| stones4 | rock1 | 88 |
| stones13 | rock1 | 82 |
| tgb | tc04 | 76 |
| rocks3 | rock1 | 69 |
| stones11 | rock1 | 56 |
| rocks1 | rock1 | 34 |
| stones14 | rock1 | 29 |
| 2x1stones2 | rock5 | 18 |
| 2x1stones3 | rock5 | 17 |
| rocks2 | rock1 | 16 |
| rocks_2x1_3 | rock1 | 15 |
| t16p | t16 | 14 |
| t05o | t05 | 12 |
| t10y | t10 | 12 |
| tc01b | tc01 | 12 |
| t06o | t06 | 10 |
| rocks_1x1_1 | rock1 | 9 |
| rocks_1x1_2 | rock1 | 9 |
| rocks_2x1_4 | rock1 | 9 |
| t07p | t07 | 8 |
| t08o | t08 | 8 |
| t08r | t08 | 8 |
| 2x1stones1 | rock5 | 6 |
| rocks_1x1_3 | rock1 | 6 |
| rocks_1x1_4 | rock1 | 6 |
| t01o | t01 | 6 |
| t05r | t05 | 6 |
| t06y | t06 | 6 |
| t07r | t07 | 6 |
| t10r | t10 | 6 |
| t11p | t11 | 6 |
| t13p | t13 | 6 |
| t13r | t13 | 6 |
| t14o | t14 | 6 |
| t16r | t16 | 6 |
| t16y | t16 | 6 |
| t05p | t05 | 4 |
| t05y | t05 | 4 |
| t07y | t07 | 4 |
| t10p | t10 | 4 |
| t11o | t11 | 4 |
| t11y | t11 | 4 |
| t12p | t12 | 4 |
| t12y | t12 | 4 |
| t15y | t15 | 4 |
| tgb.husk | tc04 | 3 |
| 1x1rocks1 | rock1 | 2 |
| 1x1rocks2 | rock1 | 2 |
| 1x1searocks2 | rock1 | 2 |
| t01p | t01 | 2 |
| t01r | t01 | 2 |
| t02r | t02 | 2 |
| t03o | t03 | 2 |
| t03p | t03 | 2 |
| t03y | t03 | 2 |
| t06r | t06 | 2 |
| t07o | t07 | 2 |
| t08b | t08 | 2 |
| t08p | t08 | 2 |
| t08y | t08 | 2 |
| t12o | t12 | 2 |
| t13o | t13 | 2 |
| t14r | t14 | 2 |
| t14y | t14 | 2 |
| t15o | t15 | 2 |
| t15p | t15 | 2 |
| t16o | t16 | 2 |
| t17o | t17 | 2 |
| t17r | t17 | 2 |
| 1x1rocks3 | rock1 | 1 |
| 1x1searocks1 | rock1 | 1 |
| 1x1searocks3 | rock1 | 1 |

## Dropped -- no same-footprint Cameo equivalent (214 types)

Grouped by kind. For the tree clumps there are close-but-not-exact Cameo
trees you can opt into (footprint differs slightly) -- listed as 'try'.


### bush (no Cameo bush actor)  (10 types, 177 placements)
- sbush1 x34
- sbush2 x32
- sbush3 x26
- lbush1 x15
- bush2 x13
- bush4 x13
- lbush2 x13
- bush1 x12
- bush3 x12
- bush5 x7

### civilian building  (8 types, 19 placements)
- engh03 x7
- come1 x4
- engch x2
- monastery x2
- castle x1
- crch x1
- engh01 x1
- engh02 x1

### grave  (5 types, 60 placements)
- graves3 x20
- graves4 x16
- graves1 x12
- graves x7
- graves2 x5

### misc / one-off  (32 types, 891 placements)
- transition x532
- dsdy x194
- swall x102
- tilled x14
- tilled2 x4
- wtrblk x4
- c11 x3
- crater1 x3
- ctg1 x3
- rd4 x3
- crater2 x2
- ctg2 x2
- heystack x2
- heystack1 x2
- tilled1 x2
- tilled20 x2
- tilled21 x2
- anjew x1
- bain x1
- blackened x1
- fiveaces x1
- happy x1
- ksk_nico x1
- mone.m x1
- mt2 x1
- rd1a x1
- rd1b x1
- rd2b x1
- rd2c x1
- sigil x1
- stgoat x1
- upps x1

### moon/space prop  (75 types, 772 placements)
- msp01 x92
- msp02 x68
- sc3 x20
- sc2 x19
- sc5 x19
- p07a x18
- p07b x18
- p16c x18
- p16d x18
- p17a x18
- p17b x18
- p17c x18
- p17d x18
- p18g x18
- p18h x18
- sc1 x16
- sc4 x16
- sc6 x16
- mcl33 x12
- mcl34 x12
- mcl35 x12
- mcl36 x12
- p07h x10
- p15a x10
- p15b x10
- p15c x10
- p15d x10
- p15e x10
- p15f x10
- p16a x10
- p16b x10
- mcl02 x8
- mcl16 x8
- p07g x8
- p17e x8
- p17f x8
- p18a x8
- p18b x8
- p18c x8
- p18d x8
- mcl09 x7
- mcl17 x7
- mcl27 x7
- mcl03 x6
- mcl06 x6
- mcl20 x6
- mcl13 x5
- mcl18 x5
- mcl23 x5
- mcl04 x4
- mcl10 x4
- mcl24 x4
- mcl29 x4
- mcl30 x4
- mcl31 x4
- mcl32 x4
- mcl05 x3
- mcl12 x3
- mcl25 x3
- liti2 x2

### other  (5 types, 19 placements)
- mttop x9
- grtilled0 x5
- rice x3
- 1x2grebld x1
- tecn2 x1

### river/ford  (7 types, 11 placements)
- fordact2 x2
- fordhorz x2
- river1 x2
- rivers_3x2_1 x2
- fordvert x1
- river3 x1
- river4 x1

### ruins  (11 types, 50 placements)
- ruinssm2 x13
- ruins2 x8
- ruins3 x8
- ruins4 x6
- ruinssm1 x6
- ruins1 x3
- 1x1ruins4 x2
- 1x1ruins6 x1
- 1x1ruins8 x1
- 2x1ruins1 x1
- 2x1ruins2 x1

### stone/rock (odd footprint)  (7 types, 57 placements)
- 1x2stones2 x16
- 1x2stones1 x13
- 1x2stones3 x10
- 2x2rocks3 x8
- 2x2rocks1 x5
- 2x2rocks2 x4
- 2x2rocks4 x1

### tree clump (no same-footprint Cameo tree)  (16 types, 602 placements)
- tgc1 x139  (try: tc01)
- tgc2 x117  (try: tc01)
- tgd x64  (try: tc01)
- tg2 x61  (try: t01)
- tg1 x60  (try: t01)
- tgd2 x50  (try: tc01)
- tree4 x34
- cypr1 x32  (try: t08)
- tree5 x17
- cypr2 x15  (try: t08)
- tree2 x6
- tree6 x3
- cypr1.husk x1
- tg1.husk x1
- tgc1.husk x1
- tgc2.husk x1

### water cliff (terrain prop)  (38 types, 152 placements)
- wcliffsh1 x10
- wcliffsh4 x10
- wcliffssmh2 x8
- wcliffsv1 x8
- wcliffsv3 x8
- wcliffsh3 x7
- wcliffssmh3 x7
- wcliffsh2 x6
- wcliffs19 x5
- wcliffs20 x5
- wcliffs21 x5
- wcliffs22 x5
- wcliffs23 x4
- wcliffs24 x4
- wcliffs25 x4
- wcliffs26 x4
- wcliffs11 x3
- wcliffs12 x3
- wcliffs13 x3
- wcliffs17 x3
- wcliffs18 x3
- wcliffs5 x3
- wcliffs6 x3
- wcliffssmv2 x3
- wcliffssmv3 x3
- wcliffsv2 x3
- wcliffsv4 x3
- wcliffs1 x2
- wcliffs10 x2
- wcliffs16 x2
- wcliffs2 x2
- wcliffs3 x2
- wcliffs7 x2
- wcliffssmh1 x2
- wcliffssmv1 x2
- wcliffs15 x1
- wcliffs4 x1
- wcliffs8 x1