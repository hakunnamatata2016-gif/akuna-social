#!/usr/bin/env python3
"""Akuna Matata post renderer.

  python3 render.py post.html out.png               # 1080x1350 image (default)
  python3 render.py story.html out.png --h 1920     # 1080x1920 image
  python3 render.py reel.html out.mp4 --h 1920 --dur 9   # video, frame-exact

What it does beyond a screenshot:
  * waits for every web font and FAILS if a brand font fell back (no silent Arial)
  * shrinks any element with class "fit" until its text fits its box
  * warns about elements that overflow the canvas or the .safe-916 zone
  * video: pauses all CSS/Web animations and steps them frame by frame,
    so motion is smooth regardless of machine speed; adds a silent AAC track
    (some apps reject video with no audio stream); writes a cover .jpg and a
    contact sheet (*_sheet.png) so you can LOOK at the motion with the Read tool.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile
from playwright.sync_api import sync_playwright

CHROME = shutil.which("google-chrome") or shutil.which("chromium")

PREP_JS = r"""
async () => {
  await document.fonts.ready;
  // auto-fit: shrink font-size until content fits its own box
  for (const el of document.querySelectorAll('.fit')) {
    let fs = parseFloat(getComputedStyle(el).fontSize), guard = 0;
    while ((el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) && fs > 12 && guard++ < 200) {
      fs -= 2; el.style.fontSize = fs + 'px';
    }
  }
  const W = innerWidth, H = innerHeight, warn = [];
  // measure every element in its settled (end-of-animation) state
  const anims = document.getAnimations();
  anims.forEach(a => { a.pause(); const e = a.effect.getComputedTiming().endTime; if (isFinite(e)) a.currentTime = e; });
  // fonts actually used vs loaded
  const used = new Map(); // family -> [weight, sample text]
  for (const el of document.querySelectorAll('body *')) {
    if (!el.childNodes.length || ![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const cs = getComputedStyle(el), fam = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim();
    const txt = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
    if (txt) used.set(fam + '|' + cs.fontWeight, [fam, cs.fontWeight, txt]);
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > W + 1 || r.left < -1 || r.bottom > H + 1 || r.top < -1) && !el.closest('[data-bleed]'))
      warn.push('outside canvas: "' + el.textContent.trim().slice(0, 40) + '"');
    if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow !== 'visible')
      warn.push('clipped text: "' + el.textContent.trim().slice(0, 40) + '"');
  }
  const missing = [];
  for (const [f, wt, txt] of used.values()) {
    if (['sans-serif', 'serif', 'monospace', 'system-ui'].includes(f)) continue;
    const loaded = [...document.fonts].some(ff => ff.family.replace(/["']/g, '') === f && ff.status === 'loaded');
    if (!loaded || !document.fonts.check(wt + ' 40px "' + f + '"', txt)) missing.push(f + ' ' + wt);
  }
  // text blocks that collide with each other (the #1 layout bug in generated posts)
  const blocks = [...document.querySelectorAll('.canvas > *, .beat > *, .safe-916 > *, [data-art]')].filter(el => {
    const cs = getComputedStyle(el); return (el.hasAttribute('data-art') || (el.innerText && el.innerText.trim())) && (cs.position === 'absolute' || el.closest('.safe-916')) && cs.opacity !== '0' && !el.classList.contains('strip') && !el.classList.contains('beat') && !el.classList.contains('safe-916');
  });
  for (let i = 0; i < blocks.length; i++) for (let j = i + 1; j < blocks.length; j++) {
    const a = blocks[i].getBoundingClientRect(), b = blocks[j].getBoundingClientRect();
    const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    const sameScene = (blocks[i].closest('.beat') || document.body) === (blocks[j].closest('.beat') || document.body);
    const artI = blocks[i].hasAttribute('data-art'), artJ = blocks[j].hasAttribute('data-art');
    if (artI && artJ) continue;                       // art may overlap art
    let hit = ox > 4 && oy > 4;
    if (hit && (artI || artJ)) {                      // text over art: only flag real collisions (>20% of the text box)
      const t = artI ? b : a; hit = (ox * oy) / (t.width * t.height) > 0.2;
    }
    if (sameScene && !(blocks[i].contains(blocks[j]) || blocks[j].contains(blocks[i])) && hit && !blocks[i].hasAttribute('data-overlap-ok') && !blocks[j].hasAttribute('data-overlap-ok'))
      warn.push('text blocks overlap: "' + (blocks[i].hasAttribute('data-art') ? '[art]' : blocks[i].textContent.trim().slice(0, 25)) + '" × "' + (blocks[j].hasAttribute('data-art') ? '[art]' : blocks[j].textContent.trim().slice(0, 25)) + '"');
  }
  const safe = document.querySelector('.safe-916');
  if (safe) {
    for (const el of document.querySelectorAll('[data-text]')) {
      const s = (el.closest('.safe-916') || safe).getBoundingClientRect();
      const r = el.getBoundingClientRect();
      if (r.left < s.left - 1 || r.right > s.right + 1 || r.top < s.top - 1 || r.bottom > s.bottom + 1)
        warn.push('outside safe zone: "' + el.textContent.trim().slice(0, 40) + '"');
    }
  }
  anims.forEach(a => { a.currentTime = 0; a.play(); });
  return { missing: [...new Set(missing)], warn: [...new Set(warn)].slice(0, 20) };
}
"""

def open_page(p, html, w, h):
    b = p.chromium.launch(executable_path=CHROME, args=["--font-render-hinting=none", "--disable-background-networking", "--no-first-run"])
    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    pg.goto("file://" + os.path.abspath(html))
    pg.wait_for_load_state("networkidle")
    rep = pg.evaluate(PREP_JS)
    if rep["missing"]:
        sys.exit(f"FONT FALLBACK — not loaded: {rep['missing']}. Fix @font-face paths before posting.")
    for line in rep["warn"]:
        print("WARN", line)
    return b, pg

def render_png(html, out, w, h):
    with sync_playwright() as p:
        b, pg = open_page(p, html, w, h)
        # still images show every animation in its finished state
        pg.evaluate("() => document.getAnimations().forEach(a => { try { a.finish() } catch (e) { a.pause() } })")
        if out.lower().endswith((".jpg", ".jpeg")):
            pg.screenshot(path=out, type="jpeg", quality=94)
        else:
            pg.screenshot(path=out)
        b.close()
    print("OK", out)

def render_mp4(html, out, w, h, dur, fps, cover_at):
    tmp = tempfile.mkdtemp(prefix="frames_")
    n = int(round(dur * fps))
    with sync_playwright() as p:
        b, pg = open_page(p, html, w, h)
        pg.evaluate("() => document.getAnimations().forEach(a => a.pause())")
        for i in range(n):
            t = i * 1000.0 / fps
            pg.evaluate("t => document.getAnimations().forEach(a => a.currentTime = t)", t)
            pg.screenshot(path=f"{tmp}/{i:05d}.jpg", type="jpeg", quality=93)
        b.close()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{tmp}/%05d.jpg",
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-r", str(fps), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out], check=True)
    base = os.path.splitext(out)[0]
    ci = min(n - 1, int(cover_at * fps))
    shutil.copy(f"{tmp}/{ci:05d}.jpg", base + "_cover.jpg")
    # contact sheet: 8 evenly spaced frames, so the motion can be reviewed as one image
    picks = [int(k * (n - 1) / 7) for k in range(8)]
    inputs = sum([["-i", f"{tmp}/{k:05d}.jpg"] for k in picks], [])
    layout = "|".join(f"{(i % 4) * 270}_{'0' if i < 4 else 'h0'}" for i in range(8))
    filt = "".join(f"[{i}:v]scale=270:-1[s{i}];" for i in range(8)) + "".join(f"[s{i}]" for i in range(8)) + f"xstack=inputs=8:layout={layout}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", filt, base + "_sheet.png"], check=True)
    shutil.rmtree(tmp)
    print("OK", out, f"({n} frames)", base + "_cover.jpg", base + "_sheet.png")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("html"); ap.add_argument("out")
    ap.add_argument("--w", type=int, default=1080); ap.add_argument("--h", type=int, default=1350)
    ap.add_argument("--dur", type=float, default=9); ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cover", type=float, default=1.5, help="second used for the video cover image")
    a = ap.parse_args()
    if a.out.lower().endswith(".mp4"):
        render_mp4(a.html, a.out, a.w, a.h, a.dur, a.fps, a.cover)
    else:
        render_png(a.html, a.out, a.w, a.h)
