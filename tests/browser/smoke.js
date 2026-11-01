// Browser regression checks for the static site (landing page and recorded season).
// Usage: serve the built site (python -m http.server -d docs 8811) then: node tests/browser/smoke.js http://127.0.0.1:8811
// Needs the playwright package. WebGL is turned off so the run is fast and deterministic on CI machines
// (software 3D rendering can take the main thread for seconds per frame); this exercises the 2D fallback and
// every panel. The 3D view itself is checked by eye on a real GPU.
const { chromium } = require("playwright");
const base = (process.argv[2] || "http://127.0.0.1:8811").replace(/\/$/, "");
const fail = [];
const check = (ok, msg) => { if (!ok) fail.push(msg); console.log(`${ok ? "ok  " : "FAIL"} ${msg}`); };

(async () => {
  const b = await chromium.launch({ args: ["--disable-webgl", "--disable-3d-apis"] });
  const errors = [];
  const page = async (w, h) => {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    p.on("pageerror", (e) => errors.push(`${w}px: ${e.message}`));
    await p.addInitScript(() => { try { localStorage.setItem("wl-toured", "true"); } catch (e) {} });
    return p;
  };
  // landing: recorded results appear with or without the 3D hero; the demo action always works
  let p = await page(1280, 800);
  await p.goto(`${base}/`, { waitUntil: "load" }); await p.waitForTimeout(2500);
  const status = await p.$$eval("#worldStatus b", (bs) => bs.map((x) => x.textContent));
  check(status.length === 4 && status.every((s) => s && s !== "–"), `landing shows the recorded season's numbers (${status.join(", ")})`);
  const demo = await p.$eval("#demoLink", (a) => a.getAttribute("href"));
  check(/app\/\?demo|demo/.test(demo), "landing has a demo link that needs no account");
  await p.close();
  // app at three widths: every destination opens
  for (const [w, h] of [[1440, 900], [768, 1024], [390, 844]]) {
    p = await page(w, h);
    await p.goto(`${base}/app/?demo`, { waitUntil: "load" }); await p.waitForTimeout(2500);
    for (const v of ["plan", "research", "incidents", "agent", "results"]) {
      const sel = w < 1020 ? `#bottomNav [data-view="${v}"]` : `.tabs [data-view="${v}"]`;
      await p.click(sel); await p.waitForTimeout(250);
      check(await p.evaluate(() => !document.getElementById("drawer").hidden), `${w}px: ${v} opens`);
    }
    await p.keyboard.press("Escape");
    if (w === 1440) {
      // replay: jump to the harvest, the report stays reachable after closing it
      await p.click("#jumpHarvest"); await p.waitForTimeout(500);
      check(await p.isVisible("#reportBtn"), "harvest report button after seeking to the end");
      await p.click("#reportBtn"); await p.waitForTimeout(300);
      check(await p.evaluate(() => /Season complete/.test(document.getElementById("drawerBody").textContent)), "harvest report opens with a verdict");
      await p.keyboard.press("Escape"); await p.waitForTimeout(200);
      check(await p.isVisible("#reportBtn"), "report reachable again after closing");
      // drone photos: the scientist's look at F6 has an expected view and SAM 3.1 segments; it enlarges and closes
      await p.keyboard.press("Escape"); await p.keyboard.press("6"); await p.waitForTimeout(400);
      check(await p.isVisible("#droneFig"), "inspector shows the drone photo the scientist analysed");
      await p.click('[data-dv="sam"]'); await p.waitForTimeout(200);
      check(await p.evaluate(() => !document.getElementById("droneBoxes").hasAttribute("hidden") && document.querySelectorAll("#droneBoxes rect").length > 50), "SAM 3.1 segments overlay the photo");
      await p.click('[data-dv="exp"]'); await p.waitForTimeout(200);
      check(await p.evaluate(() => !document.getElementById("droneExp").hidden && document.getElementById("droneImg").hidden), "the model's expected view can be shown");
      await p.click("#droneFig .drone-view"); await p.waitForTimeout(200);
      check(await p.evaluate(() => document.getElementById("droneFig").classList.contains("big") && !document.getElementById("droneLayer").hidden), "drone photo enlarges");
      await p.keyboard.press("Escape"); await p.waitForTimeout(200);
      check(await p.evaluate(() => !document.getElementById("droneFig").classList.contains("big")), "enlarged photo closes with Escape");
      await p.click('[data-dv="obs"]');
      await p.click("#reportBtn"); await p.waitForTimeout(300); await p.keyboard.press("Escape"); await p.waitForTimeout(200);
      // P2: soil carryover in the report, paired experiments, costs from your own prices, weather workspace
      await p.click("#reportBtn"); await p.waitForTimeout(300);
      check(await p.evaluate(() => /Soil salinity, start and end/.test(document.getElementById("drawerBody").textContent)), "report shows start and end soil salinity");
      await p.click('#drawerTabs [data-t="compare"]'); await p.waitForTimeout(800);
      check(await p.evaluate(() => document.querySelectorAll('#drawerBody .inc-card .pill[class*="kind-"]').length >= 4 && /Single factor/.test(document.getElementById("drawerBody").textContent) && /Input that differs/.test(document.getElementById("drawerBody").textContent)), "compare labels each pair and lists what differs");
      await p.click('#drawerTabs [data-t="economics"]'); await p.waitForTimeout(300);
      check(await p.evaluate(() => /no price/.test(document.getElementById("drawerBody").textContent)), "costs start unpriced (no invented prices)");
      await p.fill('#drawerBody [data-k="kwh"]', "0.1"); await p.dispatchEvent('#drawerBody [data-k="kwh"]', "change"); await p.waitForTimeout(300);
      check(await p.evaluate(() => /per person fed for a year/.test(document.getElementById("drawerBody").textContent)), "an entered price gives a cost per person fed");
      await p.keyboard.press("Escape"); await p.waitForTimeout(200);
      await p.click("#dt-weather"); await p.waitForTimeout(400);
      check(await p.evaluate(() => document.querySelectorAll("#wxT path").length >= 3 && /forecast issued/.test(document.getElementById("wxSide").textContent)), "weather tab shows observed weather and the last forecast");
      await p.click("#dt-timeline"); await p.waitForTimeout(100);
      // seeking back leaves no future state behind
      await p.$eval("#dateScrub", (s) => { s.value = 0; s.dispatchEvent(new Event("input")); }); await p.waitForTimeout(300);
      check(await p.evaluate(() => document.getElementById("reportBtn").hidden), "seeking back hides the report (no future leak)");
      // one incident date everywhere: the investigation and the activity log agree
      await p.click("#jumpIncident"); await p.waitForTimeout(400);
      const dates = await p.evaluate(() => {
        const inv = document.getElementById("invBody").textContent.match(/measurement of (\d+ \w+)/);
        const act = [...document.querySelectorAll("#activity li")].map((li) => li.textContent).find((t) => /Alarm in/.test(t));
        return [inv && inv[1], act && (act.match(/measured (\d+ \w+)/) || [])[1]];
      });
      check(dates[0] && dates[0] === dates[1], `incident date consistent (${dates.join(" / ")})`);
      // planner: preview mode is declared before planning, and a draft survives a reload
      await p.click("#tryPlanBtn"); await p.waitForTimeout(500);
      check(await p.isVisible("#previewBanner"), "planner declares preview mode up front");
      check(await p.evaluate(() => document.querySelectorAll("#scenarioSel option").length === 7 && /Baseline/.test(document.getElementById("plFarmSum").textContent)), "planner offers the scenario library and farm editor");
      await p.selectOption('#fieldRows select[data-i="5"]', "c:maize"); await p.waitForTimeout(200);
      check(await p.evaluate(() => /yield only/.test(document.getElementById("fieldRows").textContent)), "poor crop choice is explained (maize on F6)");
      await p.reload({ waitUntil: "load" }); await p.waitForTimeout(1500);
      await p.click("#tryPlanBtn"); await p.waitForTimeout(500);
      check(await p.evaluate(() => /Maize, autumn/.test(document.querySelector('#fieldRows select[data-i="5"]').selectedOptions[0].textContent)), "planner draft survives a reload");
    }
    check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${w}px: no horizontal page scroll`);
    await p.close();
  }
  check(!errors.length, `no script errors${errors.length ? `: ${errors.join("; ")}` : ""}`);
  await b.close();
  if (fail.length) { console.log(`\n${fail.length} check(s) failed`); process.exit(1); }
})();
