"""Wrapped-style story slides: one big reveal per screen.

The same slides open every report (scroll-snapping, animated) and become the story PNGs
(rendered at 1080x1920 with animations off), so there is one design for both.
"""

import calendar
import math
import random
import zlib
from collections import Counter

from . import render as R, stats as S

# Panel colours, in the order slides use them.
PANELS = {
    "hero": None,
    "green": ("#1ed760", "#07130b"),
    "pink": ("#ff4fa3", "#1d0010"),
    "purple": ("#7b3fe4", "#ffffff"),
    "orange": ("#ff7a1a", "#1d0a00"),
    "blue": ("#2f6bff", "#ffffff"),
    "teal": ("#19c3b1", "#001a17"),
    "dark": ("#14141b", "#f4f4f6"),
}

CSS = """
.story{position:relative;z-index:1}
.slide .art{flex:none;display:flex;align-items:center;justify-content:center;background-color:rgba(0,0,0,.22);
  background-position:center;background-size:cover;background-repeat:no-repeat;
  font-weight:900;overflow:hidden;color:inherit}
.slide .art.round{border-radius:50%}
.slide{min-height:100vh;min-height:100svh;display:flex;padding:clamp(14px,2.4vmin,36px);scroll-snap-align:start}
.slide .pn{flex:1;max-width:1180px;margin:0 auto;width:100%;border-radius:clamp(26px,4vmin,56px);
  padding:clamp(28px,6vmin,88px);display:flex;flex-direction:column;justify-content:center;gap:clamp(10px,2vmin,28px);
  position:relative;overflow:hidden}
.pn.hero{background:radial-gradient(120% 140% at 0% 0%,#ff4fa3 0%,transparent 55%),
  radial-gradient(120% 140% at 100% 100%,#1ed760 0%,transparent 50%),linear-gradient(135deg,#5b21d6,#2f6bff);color:#fff}
.sk{font-size:clamp(13px,2.4vmin,32px);font-weight:900;letter-spacing:.16em;text-transform:uppercase;opacity:.85}
.sh{font-size:clamp(40px,9vmin,150px);font-weight:900;letter-spacing:-.04em;line-height:.98;overflow-wrap:anywhere}
.sn{font-weight:900;letter-spacing:-.05em;line-height:.9;font-variant-numeric:tabular-nums}
.sm{font-size:clamp(18px,3.4vmin,52px);font-weight:800;opacity:.88;line-height:1.2}
.ss{font-size:clamp(14px,2.4vmin,36px);font-weight:700;opacity:.72}
.chip{display:inline-block;font-size:clamp(14px,2.4vmin,34px);font-weight:900;padding:.35em .8em;border-radius:999px;
  background:rgba(255,255,255,.12)}
.chip.up{color:#1ed760}.chip.down{color:#ff8a8a}
.split{display:flex;flex-direction:column;gap:clamp(18px,4vmin,56px)}
.split .tx{min-width:0;display:flex;flex-direction:column;gap:clamp(8px,1.6vmin,22px)}
.big-cover{width:min(64vmin,640px);height:min(64vmin,640px);border-radius:clamp(14px,2vmin,28px);font-size:min(26vmin,260px)}
.big-cover.round{border-radius:50%}
.slide .art{box-shadow:0 2.4vmin 6vmin rgba(0,0,0,.35)}
.split .tx{flex:1}
.pn,.tx,.cols2 > div{container-type:inline-size}
.mosaic{display:grid;grid-template-columns:repeat(3,1fr);gap:clamp(6px,1.4vmin,18px);width:min(76vmin,600px);
  transform:rotate(-5deg);flex:none;align-self:center;margin:2vmin 0}
.mosaic .art{width:100%;height:auto;aspect-ratio:1;border-radius:clamp(8px,1.4vmin,18px);font-size:clamp(20px,6vmin,72px)}
.daily{flex:1;min-width:0}
.daily .hist i{background:rgba(30,215,96,.3)}.daily .hist i.pk{background:#1ed760}
.sl{list-style:none;display:flex;flex-direction:column;gap:clamp(10px,2.2vmin,40px)}
.sl li{display:flex;align-items:center;gap:clamp(12px,2.6vmin,32px)}
.sl .n{font-size:clamp(22px,5vmin,72px);font-weight:900;width:1.1em;text-align:right;opacity:.8;flex:none}
.sl .art{width:clamp(52px,14vmin,180px);height:clamp(52px,14vmin,180px);border-radius:clamp(8px,1.4vmin,18px);font-size:clamp(22px,6vmin,76px)}
.sl .t{min-width:0;flex:1}
.sl .t b{display:block;font-size:clamp(18px,4.4vmin,58px);font-weight:900;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl .t span{display:block;font-size:clamp(13px,3vmin,38px);font-weight:600;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl .v{font-size:clamp(14px,3vmin,38px);font-weight:800;white-space:nowrap}
.sl .art.icon{background:rgba(0,0,0,.18);box-shadow:none;font-weight:400}
.gb{display:flex;flex-direction:column;gap:clamp(12px,3vmin,56px)}
.gb b{display:flex;justify-content:space-between;font-size:clamp(16px,3.6vmin,48px);font-weight:800;margin-bottom:.3em}
.gb .tr{height:clamp(10px,2.2vmin,34px);border-radius:0 8px 8px 0;background:rgba(255,255,255,.08);overflow:hidden}
.gb .tr i{display:block;height:100%;background:#1ed760;border-radius:0 8px 8px 0;transform-origin:left}
.hist{display:flex;align-items:flex-end;gap:clamp(2px,.5vmin,6px);height:clamp(80px,22vmin,300px)}
.hist i{flex:1;background:rgba(0,0,0,.28);border-radius:4px 4px 0 0;min-height:3px;transform-origin:bottom}
.hist i.pk{background:currentColor}
.hl{display:flex;justify-content:space-between;font-size:clamp(11px,2vmin,26px);font-weight:700;opacity:.7}
.mg{display:grid;grid-template-columns:repeat(auto-fill,minmax(clamp(140px,26vmin,300px),1fr));gap:clamp(8px,1.6vmin,20px)}
.mg div{display:flex;gap:clamp(8px,1.4vmin,16px);align-items:center;background:rgba(0,0,0,.18);border-radius:clamp(10px,1.6vmin,20px);
  padding:clamp(8px,1.4vmin,16px);min-width:0}
.mg .art{width:clamp(36px,7vmin,90px);height:clamp(36px,7vmin,90px);border-radius:8px;font-size:clamp(16px,3vmin,36px);box-shadow:none}
.mg small{display:block;font-size:clamp(10px,1.7vmin,22px);font-weight:900;letter-spacing:.1em;text-transform:uppercase;opacity:.75}
.mg b{display:block;font-size:clamp(13px,2.3vmin,30px);font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mg p{min-width:0}
.cols2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(16px,4vmin,56px)}
.cols2 h3{font-size:clamp(12px,2.2vmin,32px);font-weight:900;letter-spacing:.1em;text-transform:uppercase;opacity:.75;margin-bottom:.5em}
.cols2 p{font-size:clamp(15px,3.4vmin,46px);font-weight:800;line-height:1.6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cols2 p em{font-style:normal;opacity:.6;margin-right:.35em}
.mascot-xl{display:block;width:clamp(150px,34vmin,420px);aspect-ratio:16/10}
.mascot-xl svg{width:100%;height:100%;shape-rendering:crispEdges;filter:drop-shadow(0 2vmin 3vmin rgba(0,0,0,.35));
  transition:transform .2s cubic-bezier(.2,.8,.2,1)}
.mascot-xl:hover svg{transform:scale(1.06) rotate(-3deg)}
.hint{position:absolute;bottom:clamp(16px,3vmin,40px);left:50%;transform:translateX(-50%);font-size:clamp(12px,2vmin,22px);
  font-weight:800;letter-spacing:.12em;text-transform:uppercase;opacity:.8;animation:nudge 1.8s ease-in-out infinite}
@keyframes nudge{0%,100%{transform:translate(-50%,0)}50%{transform:translate(-50%,6px)}}
/* reveal on scroll */
/* Only hidden when JavaScript runs (html.js, set in <head>): previews without JS, such as an
   AirDropped file in iOS Quick Look, show every slide fully drawn. */
html.js .rv{opacity:0;transform:translateY(28px);transition:opacity .7s ease,transform .7s cubic-bezier(.2,.8,.2,1);transition-delay:calc(var(--d,0)*120ms)}
html.js .in .rv{opacity:1;transform:none}
html.js .gb .tr i,html.js .hist i{transition:transform 1s cubic-bezier(.2,.8,.2,1);transition-delay:calc(var(--d,0)*60ms + 300ms);transform:scaleX(0)}
html.js .hist i{transform:scaleY(0)}
html.js .in .gb .tr i,html.js .in .hist i{transform:none}
html.static .rv,html.static .gb .tr i,html.static .hist i{opacity:1;transform:none;transition:none}
html.static .hint{display:none}
@media (prefers-reduced-motion:reduce){html.js .rv,html.js .gb .tr i,html.js .hist i{opacity:1;transform:none;transition:none}.hint{animation:none}}
/* ---- motion: liquid blobs behind every panel, kinetic type on reveal ---- */
.pn > .liquid{position:absolute;inset:0;width:100%;height:100%;z-index:0;pointer-events:none}
.pn > .marquee{z-index:0}
.pn > :not(.liquid):not(.marquee):not(.hint){position:relative;z-index:1}
.hint{z-index:1}
.marquee{position:absolute;left:-20%;right:-20%;top:var(--top,58%);transform:rotate(-7deg);pointer-events:none;
  overflow:hidden;white-space:nowrap;line-height:1}
.marquee span{display:inline-block;padding-right:.35em;font-size:clamp(90px,24vmin,320px);font-weight:900;letter-spacing:-.04em;
  color:transparent;-webkit-text-stroke:max(1.5px,.25vmin) rgba(255,255,255,var(--a,.2));animation:mq 26s linear infinite}
.marquee.rev span{animation-direction:reverse}
@keyframes mq{to{transform:translateX(-100%)}}
/* letters rise from behind a mask; split by JS only while they animate, then the plain text is restored */
.kw{display:inline-block;overflow:hidden;vertical-align:bottom;padding:0 .02em .12em;margin:0 -.02em -.12em}
.kc{display:inline-block;transform:translateY(108%) rotate(12deg);transform-origin:0 100%;
  transition:transform .9s cubic-bezier(.2,1.25,.3,1);transition-delay:calc(var(--d,0)*120ms + var(--i,0)*26ms)}
.in .kc{transform:none}
html.js .in .sk{animation:track 1.1s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(var(--d,0)*120ms)}
@keyframes track{from{letter-spacing:.7em;opacity:0}to{letter-spacing:.16em;opacity:.85}}
html.js .in .sn{animation:pop .95s cubic-bezier(.2,1.35,.3,1) both;animation-delay:calc(var(--d,0)*120ms + 80ms);transform-origin:0 70%}
@keyframes pop{from{transform:scale(.35) skewX(-14deg);opacity:0}60%{opacity:1}to{transform:none;opacity:1}}
/* static pages (story PNGs, live reloads): everything in place, nothing moving. As specific as the rules above. */
html.static .marquee span,html.static .in .sk,html.static .in .sn{animation:none}
html.static .kc,html.static .in .kc{transform:none;transition:none}
@media (prefers-reduced-motion:reduce){.marquee span,html.js .in .sk,html.js .in .sn{animation:none}}
/* play mode: the next slide pours in from where you tapped, with a wobbling liquid edge */
html.playing .story .slide.prev{display:flex;position:fixed;inset:0;z-index:19;height:100%;min-height:0;background:#09090d;
  padding:calc(env(safe-area-inset-top,0px) + 34px) clamp(10px,2vmin,28px) calc(env(safe-area-inset-bottom,0px) + 12px)}
html.playing .story .slide.cur{z-index:20}
html.playing .story .slide.cur.pour{animation:pour .8s cubic-bezier(.65,0,.25,1) both}
@keyframes pour{
  0%{clip-path:ellipse(0% 0% at var(--x,85%) var(--y,50%))}
  45%{clip-path:ellipse(46% 38% at var(--x,85%) var(--y,50%))}
  70%{clip-path:ellipse(92% 104% at var(--x,85%) var(--y,50%))}
  100%{clip-path:ellipse(160% 160% at var(--x,85%) var(--y,50%))}}
@media (prefers-reduced-motion:reduce){html.playing .story .slide.cur.pour{animation:none}}
/* slide dots + skip link */
.dots{position:fixed;right:clamp(8px,1.6vw,22px);top:50%;transform:translateY(-50%);z-index:5;display:flex;flex-direction:column;gap:10px}
.dots a{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.28);display:block}
.dots a.on{background:#fff;transform:scale(1.25)}
.skip{position:fixed;top:14px;right:16px;z-index:6;font-size:13px;font-weight:800;color:#fff;text-decoration:none;
  background:rgba(9,9,13,.7);border:1px solid rgba(255,255,255,.12);padding:7px 12px;border-radius:999px;transition:opacity .3s}
.skip.gone{opacity:0;pointer-events:none}
html.static .dots,html.static .skip{display:none}
/* tap-through story mode (#play): one slide at a time, progress bars, tap / hold like Instagram */
.play-btn{position:fixed;top:14px;left:16px;z-index:6;font-size:13px;font-weight:800;color:#07130b;text-decoration:none;
  background:#1ed760;padding:7px 13px;border-radius:999px;box-shadow:0 4px 14px rgba(0,0,0,.35);transition:opacity .3s}
.play-btn.gone{opacity:0;pointer-events:none}
html.static .play-btn{display:none}
.pbars,.pclose{display:none}
html.playing,html.playing body{overflow:hidden;overscroll-behavior:none}
html.playing .story .slide{display:none}
html.playing .story .slide.cur{display:flex;position:fixed;inset:0;z-index:20;height:100%;min-height:0;background:#09090d;
  padding:calc(env(safe-area-inset-top,0px) + 34px) clamp(10px,2vmin,28px) calc(env(safe-area-inset-bottom,0px) + 12px);
  -webkit-user-select:none;user-select:none;-webkit-touch-callout:none;touch-action:none}
html.playing .story{z-index:30}   /* .story is its own stacking context: lift all of it above main */
html.playing .dots,html.playing .skip,html.playing .play-btn{display:none}
html.playing .pbars{display:flex;position:fixed;z-index:31;left:clamp(14px,2.4vmin,34px);right:clamp(14px,2.4vmin,34px);
  top:calc(env(safe-area-inset-top,0px) + 14px);gap:4px}
.pbars i{flex:1;height:3px;border-radius:2px;background:rgba(255,255,255,.3);overflow:hidden}
.pbars b{display:block;height:100%;width:0;background:#fff}
html.playing .pclose{display:block;position:fixed;z-index:32;right:clamp(14px,2.4vmin,34px);top:calc(env(safe-area-inset-top,0px) + 26px);
  width:36px;height:36px;border-radius:50%;border:0;background:rgba(0,0,0,.35);color:#fff;font-size:17px;font-weight:800;cursor:pointer}
html.playing.paused .pbars{opacity:.55}
.psound,.psong{display:none}
html.playing.has-sound .psound{display:block;position:fixed;z-index:32;right:calc(clamp(14px,2.4vmin,34px) + 46px);
  top:calc(env(safe-area-inset-top,0px) + 26px);width:36px;height:36px;border-radius:50%;border:0;background:rgba(0,0,0,.35);
  color:#fff;font-size:16px;cursor:pointer}
html.playing.has-sound.sound-on .psong{display:block;position:fixed;z-index:31;left:clamp(14px,2.4vmin,34px);
  top:calc(env(safe-area-inset-top,0px) + 30px);max-width:60vw;font-size:12px;font-weight:800;color:#fff;
  background:rgba(0,0,0,.35);padding:6px 11px;border-radius:999px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (min-aspect-ratio:5/4){
  .split{flex-direction:row;align-items:center}
  .big-cover{width:min(56vh,520px);height:min(56vh,520px);font-size:min(22vh,220px)}
  .mosaic{width:min(64vh,560px)}
  /* wide screens: keep tall slides within one screen */
  .sl{gap:1.6vmin}.sl .art{width:10.5vmin;height:10.5vmin;font-size:4.5vmin}
  .sl .t b{font-size:4vmin}.sl .t span{font-size:2.6vmin}.sl .n{font-size:4.4vmin}
  .cols2 p{font-size:2.9vmin;line-height:1.45}.cols2{gap:3vmin}
  .sum-cover{width:20vmin !important;height:20vmin !important;font-size:8vmin !important}
}
@media (max-aspect-ratio:4/5){
  .sk{font-size:3.1vmin}.sm{font-size:4.4vmin}.ss{font-size:3.4vmin}
  .hist{height:44vmin}.gb{gap:4.4vmin}.gb b{font-size:4.4vmin}.gb .tr{height:3.2vmin}
  .mosaic{width:84vmin;margin:4vmin 0 0}
  .sl{gap:3.6vmin}
}
"""

JS = """<script>
(function () {
  var slides = [].slice.call(document.querySelectorAll(".slide"));
  if (!slides.length) return;
  var still = document.documentElement.classList.contains("static") ||
              (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  function countUp(el) {
    var to = +el.getAttribute("data-count"), t0 = null, fmt = new Intl.NumberFormat();
    if (still || !to) return;
    function step(t) {
      t0 = t0 || t;
      var p = Math.min(1, (t - t0) / 1200), v = Math.round(to * (1 - Math.pow(1 - p, 3)));
      el.textContent = fmt.format(v);
      if (p < 1) requestAnimationFrame(step);
    }
    el.textContent = "0";
    requestAnimationFrame(step);
  }
  var dots = document.createElement("nav");
  dots.className = "dots";
  slides.forEach(function (s, i) {
    s.id = s.id || "s" + (i + 1);
    var a = document.createElement("a");
    a.href = "#" + s.id;
    a.setAttribute("aria-label", "Slide " + (i + 1));
    dots.appendChild(a);
  });
  document.body.appendChild(dots);
  var skip = document.querySelector(".skip");
  if (!("IntersectionObserver" in window) || still) {
    slides.forEach(function (s) { s.classList.add("in"); });
    return;
  }
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      var s = e.target, i = slides.indexOf(s);
      [].forEach.call(dots.children, function (d, j) { d.classList.toggle("on", j === i); });
      if (!s.classList.contains("in")) {
        if (window.mwEnter) window.mwEnter(s);
        s.classList.add("in");
        [].forEach.call(s.querySelectorAll("[data-count]"), countUp);
      }
    });
  }, {threshold: 0.45});
  slides.forEach(function (s) { io.observe(s); });
  var details = document.getElementById("details");
  if (details && skip) new IntersectionObserver(function (es) {
    var vis = es[0].isIntersecting;
    skip.classList.toggle("gone", vis);
    dots.style.opacity = vis ? "0" : "1";
  }, {threshold: 0.05}).observe(details);
})();
</script>"""

KINETIC_JS = r"""<script>
(function () {
  // Kinetic type: before a slide's reveal, its headlines are split into letters (words for long
  // ones) that rise in one after another; the plain text comes back once they've landed, so
  // kerning and line breaks are exactly as designed. Off for Reduce Motion and static pages.
  var root = document.documentElement;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function split(el) {
    if (el.getAttribute("data-k")) return;
    var text = el.textContent, words = text.split(/(\s+)/), i = 0, longWord = words.some(function (w) { return w.length > 14; });
    var perLetter = text.length <= 26 && !longWord;
    el.setAttribute("data-k", text);
    el.setAttribute("aria-label", text);
    el.textContent = "";
    words.forEach(function (w) {
      if (!w) return;
      if (/^\s+$/.test(w)) { el.appendChild(document.createTextNode(w)); return; }
      var kw = document.createElement("span");
      kw.className = "kw"; kw.setAttribute("aria-hidden", "true");
      (perLetter ? Array.from(w) : [w]).forEach(function (c) {
        var kc = document.createElement("span");
        kc.className = "kc"; kc.textContent = c; kc.style.setProperty("--i", i++);
        kw.appendChild(kc);
      });
      el.appendChild(kw);
    });
    clearTimeout(el._k);
    el._k = setTimeout(function () { unsplit(el); }, 2600 + i * 26);
  }
  function unsplit(el) {
    var t = el.getAttribute("data-k");
    if (t === null) return;
    el.textContent = t;
    el.removeAttribute("data-k");
  }
  window.mwEnter = function (slide) {
    if (reduce || root.classList.contains("static")) return;
    [].forEach.call(slide.querySelectorAll(".sh"), split);
    void slide.offsetWidth;   // let the letters start below their mask before .in is added
  };
  window.mwMorph = function (slide, on) {   // run the liquid shapes only where they can be seen
    [].forEach.call(slide.querySelectorAll("svg.liquid"), function (svg) {
      if (svg.pauseAnimations) { if (on && !reduce) svg.unpauseAnimations(); else svg.pauseAnimations(); }
    });
  };
  var slides = [].slice.call(document.querySelectorAll(".story .slide"));
  if (root.classList.contains("static")) return;
  slides.forEach(function (s) { window.mwMorph(s, false); });
  if (!("IntersectionObserver" in window)) return;
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) { if (!root.classList.contains("playing")) window.mwMorph(e.target, e.isIntersecting); });
  }, {threshold: 0});
  slides.forEach(function (s) { io.observe(s); });
})();
</script>"""
JS = KINETIC_JS + JS

PLAY_JS = r"""<script>
(function () {
  // Tap-through story mode: #play (or the Play button) shows the slides one at a time, full screen.
  // Tap right = next, tap left = back, hold = pause, Esc / ✕ = back to the page. 6 s per slide.
  var slides = [].slice.call(document.querySelectorAll(".story .slide"));
  var btn = document.querySelector(".play-btn");
  if (!slides.length) return;
  var root = document.documentElement, DUR = 6000, i = 0, on = false, paused = false;
  var elapsed = 0, t0 = 0, down = 0, downX = 0;
  var bars = document.createElement("div");
  bars.className = "pbars";
  slides.forEach(function () { var b = document.createElement("i"); b.appendChild(document.createElement("b")); bars.appendChild(b); });
  var close = document.createElement("button");
  close.className = "pclose"; close.type = "button"; close.textContent = "✕"; close.setAttribute("aria-label", "Close the story");
  document.body.appendChild(bars); document.body.appendChild(close);
  // Soundtrack (opt-in when the report was built): slides with data-preview start that song's
  // 30-second Apple Music preview; it keeps playing across slides without one. 🔊/🔇 is remembered.
  var hasSound = slides.some(function (s) { return s.getAttribute("data-preview"); });
  var au = null, song = "", fadeT = 0, soundOn = true;
  try { soundOn = localStorage.getItem("mw-sound") !== "off"; } catch (e) {}
  var sbtn = document.createElement("button"), slabel = document.createElement("div");
  sbtn.className = "psound"; sbtn.type = "button"; slabel.className = "psong";
  document.body.appendChild(sbtn); document.body.appendChild(slabel);
  if (hasSound) root.classList.add("has-sound");
  function soundUI() {
    sbtn.textContent = soundOn ? "🔊" : "🔇";
    sbtn.setAttribute("aria-label", soundOn ? "Mute the music" : "Play the music");
    root.classList.toggle("sound-on", soundOn);
  }
  soundUI();
  function fade(to, then) {   // volume fades work on a Mac; iOS ignores volume, so it just switches
    clearInterval(fadeT);
    fadeT = setInterval(function () {
      var v = au.volume + (to > au.volume ? 0.1 : -0.1);
      if (Math.abs(to - au.volume) <= 0.1) { au.volume = to; clearInterval(fadeT); if (then) then(); }
      else au.volume = Math.max(0, Math.min(1, v));
    }, 30);
  }
  function music(slide) {
    if (!hasSound) return;
    var url = slide && slide.getAttribute("data-preview");
    if (url && url !== song) {
      song = url;
      slabel.textContent = "♪ " + (slide.getAttribute("data-song") || "");
      if (!au) { au = new Audio(); au.loop = true; au.preload = "auto"; }
      var go = function () { au.src = url; au.volume = 0; if (soundOn && on && !paused) { au.play().catch(function () {}); fade(1); } };
      if (au.src && !au.paused) fade(0, go); else go();
    } else if (au && soundOn && on && !paused && au.paused && song) {
      au.play().catch(function () {});
    }
  }
  sbtn.addEventListener("click", function (e) {
    e.stopPropagation();
    soundOn = !soundOn;
    try { localStorage.setItem("mw-sound", soundOn ? "on" : "off"); } catch (x) {}
    soundUI();
    if (!au && soundOn) music(slides[i]);
    else if (au) { if (soundOn) { au.play().catch(function () {}); fade(1); } else au.pause(); }
  });
  var fmt = window.Intl ? new Intl.NumberFormat() : null;
  function countUp(el) {
    var to = +el.getAttribute("data-count"), s0 = null;
    if (!to || root.classList.contains("static")) return;
    function step(t) {
      s0 = s0 || t;
      var p = Math.min(1, (t - s0) / 1200), v = Math.round(to * (1 - Math.pow(1 - p, 3)));
      el.textContent = fmt ? fmt.format(v) : v;
      if (p < 1 && on) requestAnimationFrame(step); else el.textContent = fmt ? fmt.format(to) : to;
    }
    requestAnimationFrame(step);
  }
  function fill(j, f) { bars.children[j].firstChild.style.width = (f * 100) + "%"; }
  var pourX = "85%", pourY = "50%", prevTimer = 0;
  function show(n) {
    if (n >= slides.length) { stop(true); return; }
    var from = i;
    i = Math.max(0, n);
    slides.forEach(function (s, j) {
      s.classList.toggle("cur", j === i);
      s.classList.toggle("prev", on && j === from && from !== i);
      s.classList.remove("pour");
      fill(j, j < i ? 1 : 0);
      if (window.mwMorph) window.mwMorph(s, j === i);
    });
    var s = slides[i];
    s.style.setProperty("--x", pourX); s.style.setProperty("--y", pourY);
    pourX = "85%"; pourY = "50%";
    clearTimeout(prevTimer);
    prevTimer = setTimeout(function () { slides.forEach(function (x) { x.classList.remove("prev"); }); }, 850);
    s.classList.remove("in");
    if (window.mwEnter) window.mwEnter(s);
    void s.offsetWidth;
    s.classList.add("in", "pour");   // replay the reveal, poured in like liquid
    music(s);
    [].forEach.call(s.querySelectorAll("[data-count]"), countUp);
    elapsed = 0; t0 = performance.now();
  }
  function tick(t) {
    if (!on) return;
    if (!paused) {
      var p = (elapsed + t - t0) / DUR;
      fill(i, Math.min(1, p));
      if (p >= 1) show(i + 1);
    }
    requestAnimationFrame(tick);
  }
  function pause(yes) {
    if (yes === paused) return;
    var now = performance.now();
    if (yes) elapsed += now - t0; else t0 = now;
    paused = yes;
    if (au && song) { if (yes) au.pause(); else if (soundOn) au.play().catch(function () {}); }
    root.classList.toggle("paused", yes);
  }
  function start(n) {
    if (on) return;
    on = true; paused = false;
    root.classList.add("playing");
    if (location.hash !== "#play") history.replaceState(null, "", "#play");
    show(n || 0);
    requestAnimationFrame(tick);
  }
  function stop(toDetails) {
    if (!on) return;
    on = false;
    if (au) au.pause();
    root.classList.remove("playing", "paused");
    slides.forEach(function (s) { s.classList.remove("cur", "prev", "pour"); });
    history.replaceState(null, "", location.pathname + location.search);
    var target = toDetails ? document.getElementById("details") : slides[i];
    if (target) target.scrollIntoView();
  }
  if (btn) btn.addEventListener("click", function (e) { e.preventDefault(); start(0); });
  close.addEventListener("click", function (e) { e.stopPropagation(); stop(false); });
  document.addEventListener("pointerdown", function (e) {
    if (!on || e.target === close || e.target === sbtn || (e.target.closest && e.target.closest("a"))) return;
    down = performance.now(); downX = e.clientX;
    pause(true);
  });
  document.addEventListener("pointerup", function (e) {
    if (!on || !down) return;
    var held = performance.now() - down;
    down = 0;
    pause(false);
    if (held < 300) {   // a tap, not a hold: pour the next slide in from the finger
      pourX = (downX / window.innerWidth * 100).toFixed(1) + "%";
      pourY = (e.clientY / window.innerHeight * 100).toFixed(1) + "%";
      show(downX < window.innerWidth / 3 ? i - 1 : i + 1);
    }
  });
  document.addEventListener("pointercancel", function () { down = 0; if (on) pause(false); });
  document.addEventListener("click", function (e) {   // "See all the details" inside a slide
    var a = on && e.target.closest && e.target.closest("a");
    if (a && a.getAttribute("href") === "#details") { e.preventDefault(); stop(true); }
  });
  document.addEventListener("keydown", function (e) {
    if (!on) return;
    if (e.key === "Escape") stop(false);
    else if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); show(i + 1); }
    else if (e.key === "ArrowLeft") show(i - 1);
  });
  document.addEventListener("visibilitychange", function () { if (on) pause(document.hidden); });
  var details = document.getElementById("details");
  if (details && btn && "IntersectionObserver" in window) new IntersectionObserver(function (es) {
    btn.classList.toggle("gone", es[0].isIntersecting);
  }, {threshold: 0.05}).observe(details);
  if (location.hash === "#play") start(0);
})();
</script>"""
JS += PLAY_JS


# ---------- helpers ----------

# Two soft blobs per panel colour (a light one and a contrasting one), drawn under the content.
BLOBS = {
    "hero": ("#ff4fa3", "#1ed760"), "green": ("#c9f7da", "#19c3b1"), "pink": ("#ffb3d6", "#7b3fe4"),
    "purple": ("#ff4fa3", "#2f6bff"), "orange": ("#ffd166", "#ff4fa3"), "blue": ("#19c3b1", "#7b3fe4"),
    "teal": ("#c9f7da", "#2f6bff"), "dark": ("#1ed760", "#7b3fe4"),
}


def _blob_path(rng, cx, cy, r, n=7, jitter=0.3):
    """A smooth closed blob: n points around a circle, radius jittered, joined by Catmull-Rom curves.
    The same n always gives the same commands, so SMIL can morph between any two."""
    pts = []
    for k in range(n):
        a = 2 * math.pi * k / n + rng.uniform(-0.25, 0.25)
        rr = r * (1 + rng.uniform(-jitter, jitter))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for k in range(n):
        p0, p1, p2, p3 = pts[k - 1], pts[k], pts[(k + 1) % n], pts[(k + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d) + "Z"


def liquid(color, seed):
    """SVG of two slowly morphing, drifting blobs with soft radial fills (seeded: same slide, same shapes)."""
    rng = random.Random(seed)
    spots = ((78, 22, 34), (18, 82, 38)) if seed % 2 else ((22, 20, 32), (82, 80, 40))
    defs, shapes = [], []
    for k, ((cx, cy, r), col) in enumerate(zip(spots, BLOBS.get(color, BLOBS["dark"]))):
        gid = f"lq{seed % 100000}{k}"
        defs.append(f'<radialGradient id="{gid}"><stop offset="0" stop-color="{col}" stop-opacity=".55"/>'
                    f'<stop offset=".65" stop-color="{col}" stop-opacity=".22"/>'
                    f'<stop offset="1" stop-color="{col}" stop-opacity="0"/></radialGradient>')
        frames = [_blob_path(rng, cx, cy, r) for _ in range(3)]
        dur = rng.uniform(10, 15)
        shapes.append(
            f'<path fill="url(#{gid})" d="{frames[0]}">'
            f'<animate attributeName="d" dur="{dur:.1f}s" repeatCount="indefinite" calcMode="spline" keyTimes="0;.33;.66;1" '
            f'keySplines=".45 0 .55 1;.45 0 .55 1;.45 0 .55 1" values="{frames[0]};{frames[1]};{frames[2]};{frames[0]}"/>'
            f'<animateTransform attributeName="transform" type="translate" dur="{dur * 1.7:.1f}s" repeatCount="indefinite" '
            f'calcMode="spline" keyTimes="0;.5;1" keySplines=".45 0 .55 1;.45 0 .55 1" '
            f'values="0 0;{rng.uniform(-9, 9):.1f} {rng.uniform(-7, 7):.1f};0 0"/></path>')
    return (f'<svg class="liquid" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
            f'<defs>{"".join(defs)}</defs>{"".join(shapes)}</svg>')


def marquee(text, top="58%", rev=False, alpha=0.2):
    """Giant outlined words drifting across a panel (kinetic type), two copies for a seamless loop."""
    t = R.e(f"{text} · ")
    return (f'<div class="marquee{" rev" if rev else ""}" style="--top:{top};--a:{alpha}" aria-hidden="true">'
            f"<span>{t * 3}</span><span>{t * 3}</span></div>")


def _panel(color, inner, cls=""):
    seed = zlib.crc32(f"{color}{inner}".encode())
    blobs = liquid(color, seed)
    if color == "hero":
        return f'<section class="slide {cls}"><div class="pn hero">{blobs}{inner}</div></section>'
    bg, ink = PANELS[color]
    return f'<section class="slide {cls}"><div class="pn" style="background:{bg};color:{ink}">{blobs}{inner}</div></section>'


def _rv(html, d=0):
    return f'<div class="rv" style="--d:{d}">{html}</div>'


def _fit(text, sizes=((12, 13), (20, 11), (32, 9), (48, 7.5))):
    """vmin font size for a headline of this length (long names get smaller type)."""
    for limit, vmin in sizes:
        if len(text) <= limit:
            return vmin
    return 6.5


def _num(n, vmin, max_px):
    """A big count-up number that fits its column: digits are ~0.62 em wide, so the size is capped at
    the column width (cqw, container units) divided by the number of characters."""
    txt = f"{n:,}"
    cq = 96 / (len(txt) * 0.62)
    return (f'<div class="sn" style="font-size:clamp(40px,min({vmin}vmin,{cq:.1f}cqw),{max_px}px)" '
            f'data-count="{n}">{txt}</div>')


def mins(r):
    """'12 minutes' for a Row, with ≈ when part of it is estimated from other-device plays."""
    return f'{"≈" if r.est else ""}{round(r.seconds / 60):,} minutes'


def plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _cover(pid, name, cls="big-cover", round_=False, style=""):
    html = R.cover(pid, name, round_, big=True).replace('class="art', f'class="art {cls}', 1)
    return html.replace("<span ", f'<span style="{style}" ', 1) if style else html


# ---------- data ----------

def data_for(con, kind, plays=None, prev=None, start=None, end=None):
    """Everything the slides need. plays/prev: logged plays in the period and the period before;
    start/end: the period (dates), for the minutes-per-day chart."""
    if kind == "alltime":
        lib = S.library_totals(con)
        if not lib["plays"]:
            return None
        songs = S.library_top(con, "songs", 9)
        artists = S.library_top(con, "artists", 5)
        best = con.execute("SELECT title, artist FROM library WHERE in_library = 1 AND artist = ? "
                           "ORDER BY play_count DESC LIMIT 1", (artists[0].name,)).fetchone() if artists else None
        return {"artist_song": tuple(best) if best else None,
                "minutes": round(lib["hours"] * 60), "plays": lib["plays"], "artists_n": lib["artists"],
                "songs": songs[:5], "mosaic": songs, "artists": S.library_top(con, "artists", 5),
                "genres": S.library_top(con, "genres", 5),
                "genre_total": sum(r.plays for r in S.library_top(con, "genres", 10_000)), "all_estimated": True}
    if not plays:
        return None
    songs = S.top_songs(plays, 9)
    top_a = S.top_artists(plays, 1)
    by_artist = S.top_songs([p for p in plays if top_a and p.artist == top_a[0].name], 1)
    d = {"artist_song": (by_artist[0].name, by_artist[0].sub) if by_artist else None,
         "minutes": round(S.hours(plays) * 60), "plays": len(plays), "artists_n": len({p.artist for p in plays}),
         "songs": songs[:5], "mosaic": songs, "artists": S.top_artists(plays, 5), "genres": S.top_genres(plays, 5),
         "genre_total": sum(1 for p in plays if p.genre), "est_minutes": round(S.estimated_hours(plays) * 60),
         "minutes_x": S.hours(plays) * 60}
    if start and end:
        d["daily"] = _per_bucket(plays, start, end, kind)
    if prev is not None:
        d["prev_minutes"] = S.hours(prev) * 60  # unrounded, so % changes match the report header
    mac = [p for p in plays if p.source == "mac"]
    if mac:
        hours = Counter()
        days = Counter()
        for p in mac:
            hours[p.dt.hour] += p.seconds
            days[p.dt.weekday()] += p.seconds
        d["hours"] = [hours.get(h, 0) / 60 for h in range(24)]
        d["peak_hour"] = max(range(24), key=lambda h: hours.get(h, 0))
        d["peak_day"] = calendar.day_name[max(days, key=days.get)]
    return d


def _per_bucket(plays, start, end, kind):
    """[(label, minutes)] per day, or per month for a yearly period."""
    from datetime import timedelta
    mins = Counter()
    for p in plays:
        key = (p.dt.year, p.dt.month) if kind == "yearly" else p.dt.date()
        mins[key] += p.seconds / 60
    out = []
    if kind == "yearly":
        y = start.year
        for m in range(1, 13):
            if (y, m) > (end.year, end.month) or (end.day == 1 and (y, m) == (end.year, end.month)):
                break
            out.append((calendar.month_abbr[m], mins.get((y, m), 0)))
        return out
    day = start
    while day < end:
        label = calendar.day_abbr[day.weekday()] if kind == "weekly" else str(day.day)
        out.append((label, mins.get(day, 0)))
        day += timedelta(days=1)
    return out


def _when(h):
    if 5 <= h < 12:
        return "Morning person", "mornings"
    if 12 <= h < 17:
        return "Afternoon listener", "afternoons"
    if 17 <= h < 22:
        return "Evening ritual", "evenings"
    return "Night owl", "nights"


# ---------- slides ----------

def intro(words, label, d):
    tiles = "".join(R.cover(r.pid, r.name, big=True) for r in d.get("mosaic", [])[:9])
    mosaic = _rv(f'<div class="mosaic">{tiles}</div>', 2) if len(d.get("mosaic", [])) >= 3 else ""
    return _panel("hero", marquee("WRAPPED", "82%") + f"""
<div class="split">
  <div class="tx">
    {_rv(f'<div class="sk">{R.e(words["kicker"])}</div>')}
    {_rv(f'<a class="mascot-xl" href="{R.THIS_WEEK}" title="Open this week’s Wrapped">{R.MASCOT}</a>', 1)}
    {_rv(f'<div class="sh">{R.e(words["title"])}</div>', 2)}
    {_rv(f'<div class="sm">{R.e(label)}</div>', 3)}
  </div>
  {mosaic}
</div>
<div class="hint">Scroll ↓</div>""")


def minutes(d, words):
    chip = ""
    pm = d.get("prev_minutes")
    if pm:
        pct = (d.get("minutes_x", d["minutes"]) - pm) / pm * 100
        chip = _rv(f'<div class="chip {"up" if pct >= 0 else "down"}">{"+" if pct >= 0 else ""}{pct:.0f}% vs '
                   f'{R.e(d.get("prev_label") or words["prev"])}</div>', 5)
    hours = d["minutes"] / 60
    chart = ""
    daily = d.get("daily") or []
    if len(daily) > 1 and max(m for _, m in daily) > 0:
        vmax = max(m for _, m in daily)
        peak_i = max(range(len(daily)), key=lambda i: daily[i][1])
        bars = "".join(f'<i class="{"pk" if i == peak_i else ""}" style="height:{max(2, m / vmax * 100):.1f}%;--d:{i}"></i>'
                       for i, (_, m) in enumerate(daily))
        unit = "month" if words["span"].startswith("in ") and words["prev"] == "last year" else "day"
        ends = f'<span>{R.e(daily[0][0])}</span><span>{R.e(daily[-1][0])}</span>'
        chart = (f'<div class="rv daily" style="--d:3"><div class="ss" style="margin-bottom:1.4vmin">Minutes per {unit}</div>'
                 f'<div class="hist">{bars}</div><div class="hl">{ends}</div></div>')
    detail = _rv(f'<div class="ss">That’s {hours:,.1f} hours · {plural(d["plays"], "play")} · '
                 f'{plural(d["artists_n"], "artist")}</div>', 3)
    if d.get("all_estimated"):
        detail += _rv('<div class="ss">Estimated from play counts × song length</div>', 4)
    elif d.get("est_minutes"):
        detail += _rv(f'<div class="ss">≈{d["est_minutes"]:,} of those minutes are estimated from other devices</div>', 4)
    return _panel("dark", f"""
<div class="split">
  <div class="tx">
    {_rv('<div class="sm">You listened for</div>')}
    {_rv(f'<div style="color:#1ed760">{_num(d["minutes"], 30, 340)}</div>', 1)}
    {_rv('<div class="sh" style="font-size:clamp(32px,7vmin,110px)">minutes</div>', 2)}
    {detail}
    {chip}
  </div>
  {chart}
</div>""")


def top_song(d, words):
    s = d["songs"][0]
    return _panel("green", f"""
{_rv('<div class="sk">Your top song</div>')}
<div class="split">
  {_rv(_cover(s.pid, s.name), 1)}
  <div class="tx">
    {_rv(f'<div class="sh" style="font-size:clamp(34px,{_fit(s.name)}vmin,150px)">{R.e(s.name)}</div>', 2)}
    {_rv(f'<div class="sm">{R.e(s.sub)}</div>', 3)}
    {_rv(f'<div class="ss">Played {plural(s.plays, "time")} {R.e(words["span"])} · {mins(s)}</div>', 4)}
  </div>
</div>""")


def top_artist(d, words):
    a = d["artists"][0]
    return _panel("pink", f"""
{_rv('<div class="sk">Your top artist</div>')}
<div class="split">
  {_rv(_cover(a.pid, a.name, round_=True), 1)}
  <div class="tx">
    {_rv(f'<div class="sh" style="font-size:clamp(34px,{_fit(a.name)}vmin,150px)">{R.e(a.name)}</div>', 2)}
    {_rv(f'<div class="sm">{plural(a.plays, "play")} · {mins(a)}</div>', 3)}
    {_rv(f'<div class="ss">#1 of {plural(d["artists_n"], "artist")} {R.e(words["span"])}</div>', 4)}
  </div>
</div>""")


def ranked_list(kicker, rows, color, foot="", round_=False, value=lambda r: f"{r.plays:,}"):
    """A top-5 list slide (songs, artists or albums) with covers."""
    if not rows:
        return ""
    items = "".join(_rv(f'<li><span class="n">{i}</span>{R.cover(r.pid, r.name, round_, big=True)}<span class="t"><b>{R.e(r.name)}</b>'
                        + (f'<span>{R.e(r.sub)}</span>' if r.sub else "") + f'</span><span class="v">{value(r)}</span></li>', i)
                    for i, r in enumerate(rows[:5], 1))
    return _panel(color, f"""
{_rv(f'<div class="sk">{R.e(kicker)}</div>')}
<ol class="sl">{items}</ol>
{_rv(f'<div class="ss">{R.e(foot)}</div>', 6) if foot else ""}""")


def personality(p):
    """p: stats.personality() -> (name, description, traits)."""
    if not p:
        return ""
    name, desc, traits = p
    chips = "".join(f'<span class="chip">{R.e(t)}</span> ' for t in traits)
    return _panel("orange", f"""
{_rv('<div class="sk">Your listening personality</div>')}
{_rv(f'<div class="sh" style="font-size:clamp(40px,{_fit(name, ((12, 13), (16, 11), (22, 9)))}vmin,170px)">{R.e(name)}</div>', 1)}
{_rv(f'<div class="sm">{R.e(desc)}</div>', 2)}
{_rv(f'<div class="ss">Also: {chips}</div>', 3) if chips else ""}""")


def days_slide(days, total, first, year):
    """Days with music this year, and the first song of the year. first: a stats.Play or None."""
    if not days:
        return ""
    row = ""
    if first:
        row = _rv(f'<div class="ss" style="margin-top:2vmin">Your first song of {year}</div>'
                  f'<ol class="sl"><li>{R.cover(first.pid, first.title, big=True)}<span class="t"><b>{R.e(first.title)}</b>'
                  f'<span>{R.e(first.artist)} · {first.dt:%-d %b, %H:%M}</span></span></li></ol>', 4)
    return _panel("teal", f"""
{_rv('<div class="sk">Days with music</div>')}
{_rv(_num(days, 34, 380), 1)}
{_rv(f'<div class="sh" style="font-size:clamp(30px,7vmin,110px)">of {total} days</div>', 2)}
{_rv(f'<div class="sm">You listened on {days / total * 100:.0f}% of the days {"so far " if total < 334 else ""}this year.</div>', 3)}
{row}""")


def top_songs(d, words):
    rows = "".join(_rv(f'<li><span class="n">{i}</span>{R.cover(r.pid, r.name, big=True)}<span class="t"><b>{R.e(r.name)}</b>'
                       f'<span>{R.e(r.sub)}</span></span><span class="v">{r.plays:,}</span></li>', i)
                   for i, r in enumerate(d["songs"], 1))
    return _panel("purple", f"""
{_rv('<div class="sk">Your top songs</div>')}
<ol class="sl">{rows}</ol>
{_rv(f'<div class="ss">plays {R.e(words["span"])}</div>', 6)}""")


def top_genre(d, words):
    if not d["genres"]:
        return ""
    g, total = d["genres"][0], d["genre_total"] or 1
    top = g.plays or 1
    bars = "".join(f'<div class="rv" style="--d:{i + 3}"><b><span>{R.e(r.name)}</span><span>{r.plays / total * 100:.0f}%</span></b>'
                   f'<div class="tr"><i style="width:{r.plays / top * 100:.1f}%;--d:{i}"></i></div></div>'
                   for i, r in enumerate(d["genres"]))
    return _panel("dark", f"""
{_rv('<div class="sk">Your top genre</div>')}
{_rv(f'<div class="sh" style="color:#1ed760;font-size:clamp(40px,{_fit(g.name, ((10, 16), (16, 12), (24, 10)))}vmin,190px)">{R.e(g.name)}</div>', 1)}
{_rv(f'<div class="sm">{g.plays / total * 100:.0f}% of your plays</div>', 2)}
<div class="gb">{bars}</div>""")


def peak(d, words):
    if "peak_hour" not in d:
        return ""
    title, part = _when(d["peak_hour"])
    vmax = max(d["hours"]) or 1
    bars = "".join(f'<i class="{"pk" if h == d["peak_hour"] else ""}" style="height:{max(2, v / vmax * 100):.1f}%;--d:{h}"></i>'
                   for h, v in enumerate(d["hours"]))
    return _panel("orange", f"""
{_rv('<div class="sk">When you listen · Mac only</div>')}
{_rv(f'<div class="sh">{R.e(title)}</div>', 1)}
{_rv(f'<div class="sm">Most of your listening happened on {R.e(d["peak_day"])} {part}, peaking around {d["peak_hour"]:02d}:00.</div>', 2)}
{_rv(f'<div class="hist">{bars}</div><div class="hl"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>', 3)}""")


def changes(d, words, prev, streak, new_artists=0):
    """Compared with the period before: listening time, #1 artist and song, the streak and new artists.
    prev: the whole previous period's plays (for its #1s); d["prev_minutes"] is the like-for-like
    comparison (cut at the same point when the period is still in progress)."""
    n, first, last = streak
    top_a, top_s = d["artists"][0], d["songs"][0]
    pa, ps = S.top_artists(prev, 1), S.top_songs(prev, 1)
    if not prev and n < 2 and not new_artists:
        return ""
    label = d.get("prev_label") or words["prev"]
    head = ""
    pm = d.get("prev_minutes")
    if pm:
        pct = (d.get("minutes_x", d["minutes"]) - pm) / pm * 100
        if abs(round(pct)) < 3:  # same rounding as the minutes chip
            big, line = "Steady", f"About as much listening as {label}"
        else:
            big = f'{"+" if pct > 0 else "−"}{abs(pct):,.0f}%'
            line = f'{"More" if pct > 0 else "Less"} listening than {label}'
        head = (_rv(f'<div class="sh" style="font-size:clamp(48px,14vmin,200px)">{big}</div>', 1)
                + _rv(f'<div class="sm">{R.e(line)}</div>', 2))

    def row(i, art, title, sub, mark=""):
        return _rv(f'<li>{art}<span class="t"><b>{R.e(title)}</b><span>{R.e(sub)}</span></span>'
                   f'<span class="v">{mark}</span></li>', i + 3)

    def one(kind, now, before, round_=False):
        if not before:
            return row(0, R.cover(now.pid, now.name, round_, big=True), now.name, f"Your #1 {kind}")
        if before[0].name == now.name and before[0].sub == now.sub:
            return row(0, R.cover(now.pid, now.name, round_, big=True), now.name, f"Still your #1 {kind}", "=")
        return row(0, R.cover(now.pid, now.name, round_, big=True), now.name, f"New #1 {kind} · was {before[0].name}", "▲")

    rows = [one("artist", top_a, pa, True), one("song", top_s, ps)]
    if n >= 2:
        rows.append(row(2, '<span class="art icon">🔥</span>', f"{n} days in a row",
                        f"Listening streak · {first:%-d %b} – {last:%-d %b}"))
    if new_artists:
        rows.append(row(3, '<span class="art icon">✦</span>', plural(new_artists, "new artist"),
                        f"First played {words['span']}"))
    return _panel("teal", f"""
{_rv(f'<div class="sk">Compared with {R.e(label)}</div>')}
{head}
<ol class="sl ch">{"".join(rows)}</ol>""")


def duration(start, end):
    """'2 h 14 min' / '48 min' between two datetimes."""
    m = max(1, round((end - start).total_seconds() / 60))
    return f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"


def records(session, replay):
    """session: stats.longest_session(); replay: stats.most_replayed_day()."""
    if not session and not replay:
        return ""
    parts = [_rv('<div class="sk">Your records</div>')]
    if session:
        start, end, n = session
        parts += [_rv(f'<div class="sh">{duration(start, end)}</div>', 1),
                  _rv(f'<div class="sm">Your longest listening session · {start:%a %-d %b}, '
                      f'{start:%H:%M}–{end:%H:%M} · {plural(n, "song")}</div>', 2),
                  _rv('<div class="ss">Mac only · breaks under 10 minutes don’t end a session</div>', 3)]
    if replay:
        r, day = replay
        parts.append(_rv(f'<div class="ss" style="margin-top:2vmin">Most replayed in one day · {day:%a %-d %b}</div>', 4))
        parts.append(_rv(f'<ol class="sl"><li>{R.cover(r.pid, r.name, big=True)}<span class="t"><b>{R.e(r.name)}</b>'
                         f'<span>{R.e(r.sub)}</span></span><span class="v">{r.plays}×</span></li></ol>', 5))
        if not session:
            parts.insert(1, _rv('<div class="sh">On a loop</div>', 1))
    return _panel("blue", "\n".join(parts))


def best_bucket(title, buckets, fmt_label):
    """buckets: [(label, hours)] - e.g. weeks of a month or months of a year."""
    if not buckets or max(h for _, h in buckets) <= 0:
        return ""
    best = max(buckets, key=lambda b: b[1])
    vmax = best[1]
    bars = "".join(f'<i class="{"pk" if b is best else ""}" style="height:{max(2, b[1] / vmax * 100):.1f}%;--d:{i}"></i>'
                   for i, b in enumerate(buckets))
    labels = "".join(f"<span>{R.e(b[0])}</span>" for b in buckets)
    return _panel("blue", f"""
{_rv(f'<div class="sk">{R.e(title)}</div>')}
{_rv(f'<div class="sh">{R.e(fmt_label(best[0]))}</div>', 1)}
{_rv(f'<div class="sm">{best[1]:,.1f} hours of music</div>', 2)}
{_rv(f'<div class="hist">{bars}</div><div class="hl">{labels}</div>', 3)}""")


def streak(n, first, last):
    if not n:
        return ""
    return _panel("orange", f"""
{_rv('<div class="sk">Longest streak</div>')}
{_rv(_num(n, 40, 420), 1)}
{_rv(f'<div class="sh" style="font-size:clamp(32px,8vmin,120px)">{"day" if n == 1 else "days"} in a row</div>', 2)}
{_rv(f'<div class="sm">{first:%-d %B} – {last:%-d %B}</div>', 3)}""")


def discovery(r):
    if not r:
        return ""
    return _panel("teal", f"""
{_rv('<div class="sk">Biggest new discovery</div>')}
<div class="split">
  {_rv(_cover(r.pid, r.name, round_=True), 1)}
  <div class="tx">
    {_rv(f'<div class="sh" style="font-size:clamp(34px,{_fit(r.name)}vmin,150px)">{R.e(r.name)}</div>', 2)}
    {_rv(f'<div class="sm">New to you this year · {plural(r.plays, "play")}</div>', 3)}
  </div>
</div>""")


def months_grid(items):
    """items: (month abbr, song, artist, plays, pid)."""
    tiles = "".join(_rv(f'<div>{R.cover(pid, song or m, big=True)}<p><small>{R.e(m)}</small><b>{R.e(song or "—")}</b></p></div>', i % 6)
                    for i, (m, song, artist, n, pid) in enumerate(items))
    return _panel("purple", f"""
{_rv('<div class="sk">Top song of each month</div>')}
<div class="mg">{tiles}</div>""")


def summary(d, words):
    a = d["artists"][0]
    artists = "".join(f"<p><em>{i}</em>{R.e(r.name)}</p>" for i, r in enumerate(d["artists"], 1))
    songs = "".join(f"<p><em>{i}</em>{R.e(r.name)}</p>" for i, r in enumerate(d["songs"], 1))
    genre = R.e(d["genres"][0].name) if d["genres"] else "—"
    return _panel("hero", marquee(a.name, "-2%", rev=True, alpha=0.13) + f"""
{_rv(f'<div class="sk">{R.e(words["wrapped"])}</div>')}
<div class="split" style="flex-direction:row;align-items:center">
  {_rv(_cover(a.pid, a.name, "big-cover sum-cover", True, "width:min(30vmin,360px);height:min(30vmin,360px);font-size:min(12vmin,140px)"), 1)}
  <div class="tx">{_rv(f'<div class="ss">Top artist</div><div class="sh" style="font-size:clamp(28px,{min(_fit(a.name), 9)}vmin,120px)">{R.e(a.name)}</div>', 2)}</div>
</div>
{_rv(f'<div class="cols2"><div><h3>Top artists</h3>{artists}</div><div><h3>Top songs</h3>{songs}</div></div>', 3)}
{_rv(f'<div class="cols2"><div><h3>Minutes listened</h3>{_num(d["minutes"], 12, 130)}</div>'
     f'<div><h3>Top genre</h3><div class="sh" style="font-size:clamp(26px,7vmin,96px)">{genre}</div></div></div>', 4)}
<a class="ss rv more" style="--d:5;color:inherit" href="#details">See all the details ↓</a>""")


def words(kind, title=None):
    """Phrases for a period: kicker, intro title, 'this week'-style span, previous period, summary kicker."""
    if kind == "weekly":
        return {"kicker": "Your week in music", "title": "Your week, wrapped.", "span": "this week",
                "prev": "last week", "wrapped": "Your week, wrapped"}
    if kind == "monthly":
        return {"kicker": f"Your {title} in music", "title": f"{title}, wrapped.", "span": f"in {title}",
                "prev": "last month", "wrapped": f"Your {title}, wrapped"}
    if kind == "yearly":
        return {"kicker": f"Your {title} in music", "title": f"{title}, wrapped.", "span": f"in {title}",
                "prev": "last year", "wrapped": f"Your {title}, wrapped"}
    if kind == "alltime":
        return {"kicker": "Your all-time music", "title": "All time, wrapped.", "span": "of all time",
                "prev": "", "wrapped": "All time, wrapped"}
    return {"kicker": "Your music", "title": f"{title or 'Your music'}, wrapped.", "span": "in this period",
            "prev": "", "wrapped": f"{title or 'This period'}, wrapped"}


def build(d, words, label, extra=()):
    """[(name, html)] for a report. extra: (name, html) slides for this kind, placed before the summary."""
    parts = [("intro", intro(words, label, d)), ("minutes", minutes(d, words)), ("top-song", top_song(d, words)),
             ("top-artist", top_artist(d, words)), ("top-songs", top_songs(d, words)),
             ("top-genre", top_genre(d, words)), *extra, ("summary", summary(d, words))]
    parts = [(n, h) for n, h in parts if h]
    return soundtrack(parts, d)


def soundtrack(parts, d):
    """Play story's music (opt-in, see previews.py): which song's preview starts on which slide.
    Slides without one keep the song that's already playing."""
    from . import previews
    songs = [(r.name, r.sub) for r in d.get("songs", [])]
    if not songs or not previews.enabled():
        return parts
    plan = {"intro": songs[0], "top-song": songs[0], "top-artist": d.get("artist_song") or songs[0],
            "top-songs": songs[min(1, len(songs) - 1)], "top-genre": songs[min(2, len(songs) - 1)], "summary": songs[0]}
    urls = previews.for_songs(list(plan.values()))
    out = []
    for name, html in parts:
        url = urls.get(plan.get(name))
        if url:
            html = html.replace('<section class="slide ', f'<section data-preview="{R.e(url)}" '
                                f'data-song="{R.e(plan[name][0])} · {R.e(plan[name][1])}" class="slide ', 1)
        out.append((name, html))
    return out
