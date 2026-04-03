# KSP `.craft` Research Notes

## purpose

working notes for implementing `to_craft()` from the project rocket dict format into a KSP1 `.craft` file.

this document distinguishes between:

- **observed**: directly inspected from stock `.craft` files in the local KSP install
- **inferred**: likely enough for a functional first-pass generator, but still needs a real load test in KSP

## sources used

### local stock craft files

- `/Users/moss/Library/Application Support/Steam/steamapps/common/Kerbal Space Program/Ships/VAB/Jumping Flea.craft`
- `/Users/moss/Library/Application Support/Steam/steamapps/common/Kerbal Space Program/Ships/VAB/Ion-Powered Space Probe.craft`

### external references

- KSP forums: `What do "istg" and "dstg" mean in .craft files?`
  - https://forum.kerbalspaceprogram.com/topic/66090-what-do-quotistgquot-and-quotdstgquot-mean-in-craft-files/
- KSP forums: `Any doco on the .craft file format?`
  - https://forum.kerbalspaceprogram.com/topic/51800-any-doco-on-the-craft-file-format/

## top-level file shape

**observed**

a `.craft` file is plain text with:

1. vessel-level header fields
2. repeated `PART { ... }` blocks

example top-level header fields seen in stock files:

- `ship = ...`
- `version = ...`
- `description = ...`
- `type = VAB`
- `size = x,y,z`
- `steamPublishedFileId = 0`
- `persistentId = ...`
- `rot = 0,0,0,1`
- `missionFlag = Squad/Flags/default`
- `vesselType = Debris`

## per-part shape

**observed**

every part block contains a large amount of data. stock parts include:

- identity
  - `part = <partName>_<uniqueId>`
  - `partName = Part`
  - `persistentId = ...`
- transform / placement
  - `pos = x,y,z`
  - `attPos = x,y,z`
  - `attPos0 = x,y,z`
  - `rot = x,y,z,w`
  - `attRot = x,y,z,w`
  - `attRot0 = x,y,z,w`
  - `mir = 1,1,1`
- staging / editor metadata
  - `symMethod = Radial`
  - `autostrutMode = Off`
  - `rigidAttachment = False`
  - `istg = ...`
  - `resPri = 0`
  - `dstg = ...`
  - `sidx = ...`
  - `sqor = ...`
  - `sepI = ...`
  - `attm = ...`
  - `modCost = 0`
  - `modMass = 0`
  - `modSize = 0,0,0`
- connectivity
  - `link = <otherPartId>` for children / attached extras
  - `attN = <nodeName>,<otherPartId>_<index>|<offset>|<unknown>`
  - sometimes `srfN = ...` for radial/surface attach
  - sometimes `sym = ...` for symmetry
- content blocks
  - `EVENTS { }`
  - `ACTIONS { }`
  - `PARTDATA { }`
  - one or more `MODULE { ... }` blocks
  - optional `RESOURCE { ... }` blocks

## what `to_craft()` definitely needs

### 1. vessel header

**inferred minimum**

for a first functional VAB craft, we need to generate:

- `ship`
- `version`
- `description`
- `type = VAB`
- `size`
- `steamPublishedFileId = 0`
- `persistentId`
- `rot`
- `missionFlag`
- `vesselType`

some of these are likely cosmetic or defaultable, but stock files always include them.

### 2. unique part identifiers

**observed**

the `part = ...` field is not just the internal part name. it is:

- `<internalPartName>_<uniqueNumericId>`

example:

- `probeCoreOcto.v2_4294610328`
- `solidBooster.sm.v2_4294392496`

**inferred**

`to_craft()` will need a deterministic or random unique suffix per placed part, separate from the project’s own `pod_0`, `tank_0`, `eng_0` ids.

### 3. parent/child connectivity

**observed**

stock files encode connectivity through:

- `link = childPartId`
- `attN = nodeName,otherPartId_...`

**inferred**

for the current project’s linear vertical stack, this is enough information we must generate correctly:

- each part knows which other part it attaches to
- the correct stack node name must be used (`top` / `bottom`)
- the generated part ids inside the file must be referenced consistently in both `link` and `attN`

### 4. placement coordinates

**observed**

parts have explicit world/editor positions like:

- `pos = 0,15,0`
- `pos = 0,14.6724529,0`
- `pos = 0,13.8374624,0`

stock linear stacks step downward along the Y axis.

**inferred**

our rocket dict is not enough by itself. `to_craft()` must compute part positions.

for the current linear-stack project, a first-pass placement model can probably be:

- root pod at a fixed base position, e.g. `0,15,0`
- every child stacked directly below the parent on the Y axis
- offset determined from attach-node geometry if available in the part data
- same neutral quaternion rotation for all stack-aligned parts

this is one of the main missing pieces before `to_craft()` can work.

### 5. staging metadata

**observed**

parts include:

- `istg`
- `dstg`
- `sidx`
- `sqor`
- `sepI`

forum discussion strongly suggests:

- `istg` = activation stage / inverse staging number
- `dstg` = decoupling-related stage grouping

**important**

this is partially inferred from forum discussion, not confirmed from code.

**inferred for implementation**

our project stage mapping will need a translation layer from:

- project stage numbering: `0` fires last, larger numbers fire earlier

to:

- KSP craft-file staging fields (`istg`, probably `dstg`, maybe `sidx`, `sqor`)

this is not fully solved yet and is one of the main reasons `to_craft()` still needs a research/testing pass.

## what is probably not safe to omit yet

**observed**

stock files include many empty or repetitive sections:

- `EVENTS { }`
- `ACTIONS { }`
- `PARTDATA { }`

and also detailed `MODULE` state blocks.

**inference**

for a first implementation, the safest route is not to synthesize module state from scratch.
instead:

- use stock craft files as templates / exemplars
- preserve part-module blocks from known-good part snapshots where possible
- only rewrite the fields that must differ per assembled vehicle:
  - part ids
  - parent/child references
  - positions
  - rotations
  - staging
  - resource amounts when needed

building every `MODULE` block from nothing is likely brittle.

## practical conclusion

we do **not** yet have enough confidence to write a robust `to_craft()` directly from the project rocket dict alone.

we **do** have a clear list of what must be solved:

1. generate top-level vessel header
2. generate unique KSP part ids
3. map parent/child relations into `link` and `attN`
4. compute linear-stack Y-axis placement
5. translate project stage numbers into KSP staging metadata
6. decide how to source or template `MODULE` / `RESOURCE` sub-blocks safely

## recommended next step

before implementing `to_craft()`, do one narrow prototype:

- choose a minimal 3-part vertical rocket:
  - pod
  - tank
  - engine
- compare a stock `.craft` file for a similar stack
- produce a single synthetic `.craft`
- load it in KSP and see what fails

that prototype will answer the still-open question:

> can we get away with a minimal generated part block plus copied/default module sections, or do we need a richer per-part template system?
