# rocket physics primer

written for someone comfortable with math and differential equations but new to rocketry.

---

## the core problem

a rocket needs to go fast enough to either escape the atmosphere (Goal 1) or stay in orbit (Goals 2+). the fundamental question is: **given a rocket's mass and engines, how much can we change its velocity?** that change in velocity is called **delta-v** (Δv), and it's the universal currency of spaceflight.

everything in mission planning is budgeted in delta-v:
- reaching low Kerbin orbit: ~3400 m/s
- reaching the Mun: ~860 m/s more
- landing on the Mun: ~580 m/s more

if your rocket has enough delta-v, it can do the mission. if not, it can't, no matter what.

---

## the rocket equation

this is the central result. if you know one equation, it's this one:

$$\Delta v = I_{sp} \cdot g_0 \cdot \ln\left(\frac{m_0}{m_f}\right)$$

where:
- $\Delta v$ — the velocity change the rocket can achieve (m/s)
- $I_{sp}$ — specific impulse, a measure of engine efficiency (seconds)
- $g_0$ — standard gravity, 9.80665 m/s² (a unit-conversion constant baked into the $I_{sp}$ definition)
- $m_0$ — wet mass: the rocket's total mass including all fuel
- $m_f$ — dry mass: the rocket's mass after all fuel is burned

the derivation is a simple ODE. a rocket expels mass (exhaust) to accelerate. newton's third law: the exhaust going backward pushes the rocket forward. as fuel burns, the rocket gets lighter, so the same thrust accelerates it more. integrate force over time and you get the log:

$$\Delta v = \int_{m_0}^{m_f} \frac{F}{m} \, dm = v_e \ln\left(\frac{m_0}{m_f}\right)$$

where $v_e = I_{sp} \cdot g_0$ is the effective exhaust velocity.

**the key insight**: delta-v depends on the **mass ratio** $m_0 / m_f$, not the absolute masses. a small rocket and a giant rocket with the same mass ratio get the same delta-v. this is why the log matters — like a fold-change in gene expression, what counts is the ratio, not the raw number.

because it's a log, the returns diminish steeply. doubling your fuel doesn't double your delta-v — it adds only $\ln(2) \approx 0.69$ times your exhaust velocity. to get to orbit on a single stage, you'd need an absurd mass ratio. this is why staging exists.

---

## specific impulse (Isp)

$I_{sp}$ is the efficiency rating of an engine — how much thrust you get per unit of fuel burned. higher is better.

it's defined as:

$$I_{sp} = \frac{F}{\dot{m} \cdot g_0}$$

where $F$ is thrust and $\dot{m}$ is the mass flow rate of propellant. the $g_0$ factor is just a historical convention that makes the units work out to seconds regardless of whether you use metric or imperial.

in KSP (and reality), $I_{sp}$ varies by engine type:
- solid rocket boosters: ~170 s (cheap, simple, inefficient)
- liquid fuel + oxidizer (LFO) engines: ~270–450 s (the workhorse)
- nuclear engines: ~800 s (very efficient but heavy and low thrust)

the analog for a biologist: think of $I_{sp}$ like the effect size of a mutation. a high-$I_{sp}$ engine squeezes more delta-v out of a given mass of propellant.

---

## thrust-to-weight ratio (TWR)

delta-v tells you *how much* you can change velocity total. TWR tells you *whether you can lift off at all*.

$$TWR = \frac{F_{thrust}}{m \cdot g}$$

where $F_{thrust}$ is total engine thrust, $m$ is total rocket mass, and $g$ is surface gravity.

- TWR < 1: the rocket can't lift off. thrust doesn't overcome gravity.
- TWR = 1: the rocket hovers.
- TWR > 1: the rocket accelerates upward.

for a Kerbin launch you typically want TWR > 1.3 or so. too low and you spend too long fighting gravity. too high and your aerodynamic drag losses spike (and your Kerbal gets squished).

this is your first hard filter: **if TWR < 1, the design is physically impossible — don't bother simulating it.**

note that TWR changes during flight as fuel burns and mass drops. what matters is the **initial TWR** at launch (hardest moment — maximum mass, full gravity).

---

## staging

staging is the solution to the diminishing-returns problem in the rocket equation.

once a fuel tank is empty, it's dead mass — it doesn't contribute fuel but it still needs to be accelerated. if you could throw it away, your mass ratio for the remaining burn would improve dramatically.

staging does exactly that: you jettison empty tanks (and their engines) partway through the flight. each stage gets its own fresh mass ratio calculation:

$$\Delta v_{total} = \sum_i I_{sp,i} \cdot g_0 \cdot \ln\left(\frac{m_{0,i}}{m_{f,i}}\right)$$

each stage $i$ has its own wet mass $m_{0,i}$, dry mass $m_{f,i}$, and $I_{sp,i}$. the total delta-v is the sum.

the gain is significant. a two-stage rocket can reach orbit where a single-stage equivalent cannot, using the same total fuel mass. this is why every real orbital vehicle uses staging.

in KSP, stages fire in reverse numerical order: stage N fires first, stage 0 fires last. the staging dict in the rocket format maps part ids to stage numbers.

---

## the gravity turn

in practice, you don't fly straight up. going straight up is inefficient because:

1. you're fighting gravity the whole time (gravity drag)
2. to reach orbit you need horizontal velocity, not just altitude

the optimal ascent is a **gravity turn**: launch vertically, then gradually pitch over as you gain speed. by the time you're above the atmosphere (~70 km on Kerbin) you're flying nearly horizontal and your velocity is mostly orbital.

for the analytic filter, we don't need to simulate the gravity turn — we just check whether the rocket has enough total delta-v and enough TWR to plausibly complete one. the detailed trajectory is what the surrogate simulator handles.

---

## putting it together: the analytic filter stack

for a given rocket design, the analytic filters compute:

1. **valid propellant check** — does the rocket have fuel for its engines? (already done in structure validator)
2. **TWR check** — is initial TWR > some threshold (e.g. 1.2)? if not, reject.
3. **delta-v estimate** — using the rocket equation per stage, is total delta-v > 3400 m/s (Kerbin orbit budget)? if not, reject.
4. optionally: **burn time** — does each stage burn long enough to be useful, or does it flame out in 2 seconds?

these three numbers — TWR, Δv, burn time — are cheap to compute from the parts library data we already have. they don't require simulation. and they're powerful enough to eliminate most bad designs before KSP ever sees them.

---

## what you need from the parts library

to compute these, you need per-part data. the good news: the scraper already extracts it.

| quantity | where it comes from |
|----------|-------------------|
| engine thrust (kN) | `part['engine']['max_thrust']` |
| engine Isp (s) | `part['engine']['isp']` |
| engine propellants | `part['engine']['propellants']` |
| tank resource mass | `part['resources']` — stores amounts, need density to convert to kg |
| part dry mass | `part['mass']` |

the one thing we'll need to look up: **resource densities** (kg per unit of LiquidFuel, Oxidizer, etc.). KSP defines these in its resource config files — we'll either scrape them or hardcode the standard values (they don't change).

---

## kerbin-specific numbers

| quantity | value |
|----------|-------|
| surface gravity | 9.81 m/s² |
| atmosphere height | 70 km |
| orbital velocity (LKO) | ~2246 m/s |
| delta-v to LKO | ~3400 m/s |
| delta-v to Mun transfer | ~860 m/s |
| delta-v to Mun landing | ~580 m/s |

note: Kerbin is about 1/10 the size of Earth but has Earth-like gravity (same $g$, smaller radius). this is a deliberate KSP design choice to make orbits achievable without absurd delta-v budgets.
