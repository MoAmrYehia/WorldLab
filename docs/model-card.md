# WorldLab model card: what it is, what is real, what it is not

## Who it is for

**Primary user: an agronomy or irrigation research team assessing strategies for water-limited farms** (for example a
university or extension group working on drip-irrigated farms on brackish groundwater in the UAE).

- **Their input:** a farm description (fields, soils and starting salinity, water quota, energy budget), candidate crops,
  and weather.
- **Their decision:** which crops and irrigation strategy to use under a hard water and energy budget, and how to
  investigate and respond when field measurements stop matching expectations.
- **What WorldLab gives them:** a scientist that states predictions before acting, tests them, and records every decision
  with its evidence in a tamper-evident ledger; event-level scores for detection, diagnosis and response; matched
  comparisons of strategies on the same farm and weather; an offline evidence bundle for each recorded run.
- **Why existing tools need extra work for this:** crop models such as FAO AquaCrop simulate a season you have already
  specified. They do not choose experiments, diagnose a divergence, or keep an auditable record of why a strategy changed.
  WorldLab puts a simplified crop and soil model inside that experiment, diagnose, act and record loop. It is not a
  replacement for AquaCrop, and nothing here should be read as AquaCrop output.

## What is real and what is simulated

| Input or quantity | Status | Source or note |
|---|---|---|
| Season weather in the *Real 2024–25 weather* scenario | **Real data (reanalysis and satellite)** | NASA POWER Daily API v2.10.1, community AG, 24.2075 N, 55.7447 E (Al Ain), 1 Oct 2024 to 30 Jun 2025: daily Tmax, Tmin, RH, wind at 2 m, all-sky shortwave, corrected precipitation. File `worldlab/data/nasa_power_alain_2024_25.csv`, SHA-256 `c66ae088…c1a8d63d`, checked on every load. This is a ~50 km grid cell, not a station on a farm. |
| Reference evapotranspiration (ET0) | Computed | FAO-56 Penman-Monteith (Allen et al. 1998) from the weather above (or from the synthetic weather). |
| Season weather in all other scenarios, trial seasons, and the imagined seasons the scientist plans and trains in | Synthetic | Stochastic draws around an approximate inland-UAE monthly climatology (`farm/weather.py`). |
| Soils, starting salinity, drip efficiency, the local varieties' true traits, hidden faults | Synthetic | Generated per farm seed. |
| Drone photos | Synthetic | Rendered from the simulator's state; SAM 3.1 and Muse Spark analyse these renders, not real fields. |
| Crop priors (growth, water use, salt tolerance) | Published values, approximate | See below. |
| Nutrition of harvested products | Published values, approximate | USDA FoodData Central. |

**Tracing one real input:** start a season with the *Real 2024–25 weather* scenario. The ledger's `session` entry names
the weather source and its SHA-256; each day's measured weather (Tmax, RH, wind, radiation, rain, ET0) appears in the
farm's daily record and the weather tab; it drives crop growth, heat stress at flowering, crop water use, irrigation
demand and the forecasts the scientist sees. The import reports missing values (none in this extract), values outside
physical ranges (none), and how any gap would be filled (up to 3 days by interpolation, longer gaps from the
climatology, each counted).

**What the real season shows:** October 2024 to June 2025 at Al Ain was hotter and drier than the simulator's
climatology. Monthly mean Tmax was 0.8 to 4.7 °C higher (April: 40.3 °C real, 35.6 °C synthetic); there was almost no rain
(about 2 mm over the season, against about 64 mm in the synthetic climatology); and ET0 was higher in eight of nine
months, totalling 1,765 mm. The synthetic climatology is too wet in winter and too mild in spring. That makes seasons
on synthetic weather look easier than 2024–25 was.

**ET0 check against a published reference:** for the FAO-56 worked example 18 (Brussels, 6 July; published ET0 3.9
mm/day), WorldLab's implementation gives 3.79 mm/day (−3%). The difference comes mainly from WorldLab using daily mean
relative humidity where the example uses RHmax and RHmin. This checks the ET0 arithmetic only. It does not validate
yield, diagnosis or water savings: **real weather alone validates none of those.**

## Crop priors: sources

These are the scientist's starting beliefs. Each farm's true local varieties differ from them in four traits, which the
scientist learns from trial plots.

- **Salt tolerance** (threshold ECe and yield decline per dS/m): FAO Irrigation and Drainage Paper 29 Rev. 1, Ayers and
  Westcot (1985), Table 4, after Maas and Hoffman (1977). For example wheat 6.0 dS/m and 7.1%/dS/m; maize 1.7 and 12;
  rice 3.0 and 12; sorghum 6.8 and 16; beans 1.0 and 19. Cassava and millet are not in that table; their salt values are assumptions.
- **Basal crop coefficients (Kcb)**: FAO-56, Allen et al. (1998), Table 17 (mid-season values, for example wheat 1.10 and
  maize 1.15).
- **Normalised water productivity (WP\*), harvest index, maximum canopy cover**: approximate values from the AquaCrop
  reference manual's crop files (Steduto, Hsiao, Raes and Fereres 2009; Raes et al., FAO AquaCrop reference manual), for
  example WP\* wheat 15 g/m², maize 33 g/m², rice 19 g/m². WorldLab's crop model is a simplified, AquaCrop-style model
  written for this project, not AquaCrop.
- **Thermal time, base temperatures, heat thresholds at flowering, root depths, depletion fractions**: approximate values
  in the ranges given by FAO-56 and the AquaCrop crop files. These were not checked entry by entry against a single table
  and should be treated as assumptions.
- **Nutrition per kg of harvested product** (energy, protein, vitamin A): approximate USDA FoodData Central values.

## What "people fed" means

A **simulated index**, not people actually fed: the harvest's energy, protein and vitamin A divided by one person's yearly
need (2,100 kcal, 50 g protein and 600 µg vitamin A RAE a day), taking the smallest of the three. It ignores other
nutrients, losses after harvest, dietary diversity and distribution. It is not a claim of nutritional adequacy for any
population. Reports also show harvested tonnes, water productivity, energy use and fault-recovery measures.

## Trials happen before the season, in the model's time

Trial plots are grown "for one season" before the main season starts. That stands for data from **earlier seasons**:
a real deployment would use last year's trial plots or a research station's plot data, entered as observations. Trials
are not instantaneous physical experiments.

## Limitations

- The crop and soil model is simplified and has not been validated against field data from this region.
- Faults, sensor errors and diseases are simulated; their detectability depends on simulated noise levels.
- Drone images are renders of the simulator's state, so the perception results show what SAM 3.1 and Muse Spark do on
  realistic synthetic images, not on real fields.
- Costs: no prices are built in. The costs view uses only prices the user enters.
- No practitioner has reviewed WorldLab yet. A review request is listed in the submission checklist; any feedback will
  be recorded here as received, with what changed.
- Field validation is a separate future milestone. Nothing here is field-validated.

## A feasible next pilot

One farm, one season, three fields on drip irrigation:
1. Import the farm's own daily weather station data (same importer, a different file) and soil-moisture sensor readings
   as observations.
2. Enter last season's yields per field as trial data.
3. Run the scientist in *advisory* mode (human decision mode, already built): it proposes tests and actions, and the
   agronomist approves or declines each one.
4. Compare its alarms and diagnoses with the agronomist's own log. Measure detection delay, false alarms, and water used
   against the farm's usual practice.

Sources: [NASA POWER](https://power.larc.nasa.gov/) · [FAO-56](https://www.fao.org/3/x0490e/x0490e00.htm) ·
[FAO-29](https://www.fao.org/3/t0234e/t0234e00.htm) · [AquaCrop](https://www.fao.org/aquacrop/) ·
[USDA FoodData Central](https://fdc.nal.usda.gov/)
