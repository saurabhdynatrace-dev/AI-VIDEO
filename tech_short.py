# ===== "SQL / Python in 30 seconds" - YouTube Short maker (English) =====
# Runs in Google Colab (paste into ONE cell) and on GitHub Actions (tech-short.yml, fully automatic).
# 1) The AI writes a small example (SQL table + query, or Python code)
# 2) The code is REALLY RUN (SQLite / Python) -> the output on screen is always correct
# 3) The AI writes the narration from the real output
# 4) Code with colours + tables + voice (same Edge voice as the Kidzivora pipeline) + word captions -> 1080x1920 Short
import os, sys, re, json, time, math, sqlite3, asyncio, subprocess, textwrap, getpass, io, urllib.parse
from concurrent.futures import ThreadPoolExecutor

IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    os.system("apt-get -qq install -y ffmpeg fonts-dejavu-core > /dev/null")
    os.system("pip install -q edge-tts pygments")

import requests
from PIL import Image, ImageDraw, ImageFont
from pygments import highlight
from pygments.lexers import SqlLexer, PythonLexer
from pygments.formatters import ImageFormatter

# ---------------- SETTINGS (change freely) ----------------
ON_GITHUB = bool(os.environ.get("GITHUB_ACTIONS"))
TOPIC = os.environ.get("TOPIC", "").strip() if ON_GITHUB else \
        "SQL window function ROW_NUMBER to find the top salary in each department"   # Colab: any SQL / Python topic ("" = AI picks)
CHANNEL = "@learnbySaurabhSrivastava"
VOICE = "en-IN-NeerjaNeural"     # same English voice as the Kidzivora pipeline; male: "en-IN-PrabhatNeural"
VOICE_RATE = "+4%"
MUSIC_VOL = 0.07                 # soft background music (0 = no music)
W, H, FPS = 1080, 1920, 25
OUT = "short_out"; os.makedirs(OUT, exist_ok=True)

def key(name, ask, required=False):
    v = os.environ.get(name, "").strip()
    if v: return v
    try:
        from google.colab import userdata
        v = (userdata.get(name) or "").strip()
        if v: return v
    except Exception:
        pass
    if ON_GITHUB:
        if required: raise SystemExit(f"Missing secret {name}: add it in repo Settings -> Secrets and variables -> Actions")
        return ""
    v = getpass.getpass(ask).strip()
    if required and not v:
        raise SystemExit(f"{name} is needed")
    return v

NVIDIA_KEY = key("NVIDIA_KEY", "Paste your NVIDIA API key (nvapi-...): ", required=True)
CF_TOKEN = key("CF_TOKEN", "Paste your Cloudflare token (backup AI) or press Enter to skip: ")
CF_ID = "31fdd1f22c348a91b6da9d4a4e9c3b64"
NV_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia/nemotron-3.5-super-vl-120b-a12b"]
CF_MODELS = ["@cf/meta/llama-3.3-70b-instruct-fp8-fast"]

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BG_TOP, BG_BOT = (15, 23, 42), (2, 6, 23)
CARD, ACCENT, ACCENT2, TEXT, MUTED = (30, 41, 59), (56, 189, 248), (250, 204, 21), (241, 245, 249), (148, 163, 184)

def font(path, size):
    try: return ImageFont.truetype(path, size)
    except Exception: return ImageFont.load_default()

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-1500:])
    return p.stdout

# ---------------- 1. AI ----------------
def parse_json(t):
    t = re.sub(r"<think>[\s\S]*?</think>", "", str(t or ""))
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M)
    return json.loads(t[t.find("{"): t.rfind("}") + 1])

def ask_ai(prompt, ok):
    last = None
    for m in NV_MODELS:
        try:
            r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", timeout=180,
                              headers={"Authorization": f"Bearer {NVIDIA_KEY}"},
                              json={"model": m, "temperature": 0.6, "max_tokens": 8000,
                                    "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            d = parse_json(r.json()["choices"][0]["message"].get("content") or "")
            if ok(d):
                print(f"  AI: {m}"); return d
            raise ValueError("reply missing fields")
        except Exception as e:
            last = e; print(f"  {m} failed ({str(e)[:80]})")
    if CF_TOKEN:
        for m in CF_MODELS:
            try:
                r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{CF_ID}/ai/run/{m}", timeout=180,
                                  headers={"Authorization": f"Bearer {CF_TOKEN}"},
                                  json={"messages": [{"role": "user", "content": prompt}], "max_tokens": 2500})
                r.raise_for_status()
                d = parse_json(r.json()["result"]["response"])
                if ok(d):
                    print(f"  AI: Cloudflare {m}"); return d
            except Exception as e:
                last = e; print(f"  cloudflare {m} failed ({str(e)[:80]})")
    raise RuntimeError(f"No AI model worked: {last}")

def make_example(topic, error=""):
    fix = f"\nYour previous code FAILED with this error, fix it:\n{error}\n" if error else ""
    prompt = f"""You create a 30-40 second YouTube Short that teaches ONE concept: "{topic}".
Audience: data analysts, beginners and interview preparation.{fix}
Return ONLY valid JSON, no markdown:
{{"title": "short catchy title, max 55 characters", "kind": "sql or python", "setup": "...", "code": "..."}}
Rules if kind = sql:
- setup: SQLite statements that CREATE ONE small table (2-4 columns, realistic names like employees, orders, students) and INSERT 5-6 rows.
- code: ONE SQLite query (max 10 lines, window functions and CTEs are fine) whose result has at most 6 rows.
Rules if kind = python:
- setup: "" ; code: max 12 lines, standard library or pandas only, no input(), no files, no internet; it prints a short result (max 8 lines).
Keep names short so the table fits on a phone screen (cell values max 12 characters).
Every code line must be max 32 characters long (break long lines), so the code is readable on a phone."""
    return ask_ai(prompt, lambda d: d.get("code") and d.get("kind") in ("sql", "python") and d.get("title"))

def run_example(ex):
    # really runs the code; returns dict with input table + output (rows or text)
    if ex["kind"] == "sql":
        db = sqlite3.connect(":memory:")
        db.executescript(ex.get("setup") or "")
        tname = db.execute("select name from sqlite_master where type='table' limit 1").fetchone()
        inp = None
        if tname:
            c = db.execute(f'select * from "{tname[0]}" limit 6')
            inp = dict(name=tname[0], cols=[x[0] for x in c.description], rows=c.fetchall())
        c = db.execute(ex["code"].strip().rstrip(";"))
        if not c.description:
            raise RuntimeError("the query returned no columns")
        rows = c.fetchmany(7)
        if not rows:
            raise RuntimeError("the query returned 0 rows - change the data or the query so it returns rows")
        return dict(input=inp, cols=[x[0] for x in c.description], rows=rows[:6], text=None)
    p = subprocess.run([sys.executable, "-c", ex["code"]], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-600:])
    out = p.stdout.strip()
    if not out:
        raise RuntimeError("the code printed nothing")
    return dict(input=None, cols=None, rows=None, text="\n".join(out.splitlines()[:9]))

def result_as_text(res):
    if res["text"] is not None: return res["text"]
    return " | ".join(res["cols"]) + "\n" + "\n".join(" | ".join(str(v) for v in r) for r in res["rows"])

def make_narration(ex, res):
    inp = ""
    if res["input"]:
        i = res["input"]
        inp = f"Input table {i['name']}: " + " | ".join(i["cols"]) + "\n" + "\n".join(" | ".join(map(str, r)) for r in i["rows"])
    prompt = f"""Write the voice-over for a 30-40 second YouTube Short about: {ex['title']}
Code ({ex['kind']}):
{ex['code']}
{inp}
REAL output of the code (it was really run):
{result_as_text(res)}

Speak like a friendly senior data analyst explaining to a junior: natural spoken English, short sentences, no jargon without explaining it.
Return ONLY valid JSON:
{{"hook": "one question that makes people stay, 8-14 words",
  "table": "1 sentence about the input data, 10-16 words (\\"\\" if there is no input table)",
  "code": ["2 or 3 short lines that explain the code step by step, each 10-16 words"],
  "output": "1 sentence that explains the REAL output above, 10-16 words",
  "takeaway": "1 sentence: when to use this in real work, plus 'Follow for daily SQL and Python tips', max 22 words"}}
Every fact must match the code and the real output exactly."""
    return ask_ai(prompt, lambda d: d.get("hook") and d.get("code") and d.get("output") and d.get("takeaway"))

# ---------------- 2. PICTURES ----------------
def base_frame(label):
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):   # soft vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3)))
    d.rounded_rectangle([60, 70, 60 + d.textlength(CHANNEL, font=font(FONT_BOLD, 34)) + 50, 130], 30, fill=CARD)
    d.text((85, 80), CHANNEL, font=font(FONT_BOLD, 34), fill=ACCENT)
    y = 170
    for ln in textwrap.wrap(EX["title"], 26)[:3]:
        d.text((60, y), ln, font=font(FONT_BOLD, 62), fill=TEXT); y += 76
    if label:
        d.text((60, y + 30), label, font=font(FONT_BOLD, 40), fill=ACCENT2)
    return img, y + 100

def table_img(cols, rows, max_w=960, min_w=760):
    f, fb = font(FONT_MONO, 42), font(FONT_MONO_B, 42)
    cells = [[str(c)[:14] for c in cols]] + [[str(v)[:14] for v in r] for r in rows]
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    widths = [max(tmp.textlength(row[i], font=fb) for row in cells) + 40 for i in range(len(cols))]
    rh = 76
    img = Image.new("RGB", (int(sum(widths)), rh * len(cells)), CARD)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, rh], fill=(14, 116, 144))
    for r, row in enumerate(cells):
        x = 0
        if r > 0 and r % 2 == 0:
            d.rectangle([0, r * rh, img.width, (r + 1) * rh], fill=(36, 50, 72))
        for i, v in enumerate(row):
            d.text((x + 20, r * rh + 15), v, font=fb if r == 0 else f, fill=TEXT)
            x += widths[i]
    if img.width > max_w or img.width < min_w:
        tw = max_w if img.width > max_w else min_w
        img = img.resize((tw, int(img.height * tw / img.width)), Image.LANCZOS)
    return img

def code_img(code, kind, max_w=960):
    png = highlight(code.strip(), SqlLexer() if kind == "sql" else PythonLexer(),
                    ImageFormatter(font_name="DejaVu Sans Mono", font_size=40, line_numbers=False,
                                   style="monokai", image_pad=28, line_pad=10))
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
    return img

def text_block_img(text, max_w=960):
    f = font(FONT_MONO, 36)
    lines = [ln[:44] for ln in text.splitlines()][:9]
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    w = int(max(tmp.textlength(ln, font=f) for ln in lines) + 60)
    img = Image.new("RGB", (max(w, 400), 56 * len(lines) + 50), (12, 12, 16))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        d.text((30, 25 + i * 56), ln, font=f, fill=(134, 239, 172))
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)), Image.LANCZOS)
    return img

def card_frame(label, content, path):
    img, top = base_frame(label)
    d = ImageDraw.Draw(img)
    x = (W - content.width) // 2
    top = max(top, (top + 1560 - content.height) // 2)
    d.rounded_rectangle([x - 24, top - 24, x + content.width + 24, top + content.height + 24], 28, fill=CARD)
    img.paste(content, (x, top))
    img.save(path)

def hook_frame(path):
    img, top = base_frame("")
    d = ImageDraw.Draw(img)
    big = font(FONT_BOLD, 92)
    q = "Can you solve this?" if EX["kind"] == "sql" else "Guess the output!"
    d.text(((W - d.textlength(q, font=big)) / 2, 760), q, font=big, fill=ACCENT2)
    tag = "SQL" if EX["kind"] == "sql" else "PYTHON"
    tf = font(FONT_BOLD, 120)
    tw = d.textlength(tag, font=tf)
    d.rounded_rectangle([(W - tw) / 2 - 50, 920, (W + tw) / 2 + 50, 1090], 40, fill=ACCENT)
    d.text(((W - tw) / 2, 935), tag, font=tf, fill=(2, 6, 23))
    img.save(path)

def takeaway_frame(text, path):
    img, top = base_frame("")
    d = ImageDraw.Draw(img)
    f = font(FONT_BOLD, 62)
    y = 700
    for ln in textwrap.wrap(text, 26)[:6]:
        d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=TEXT); y += 84
    s = "Follow for daily SQL & Python"
    fs = font(FONT_BOLD, 48)
    sw = d.textlength(s, font=fs)
    d.rounded_rectangle([(W - sw) / 2 - 40, y + 60, (W + sw) / 2 + 40, y + 160], 50, fill=(220, 38, 38))
    d.text(((W - sw) / 2, y + 82), s, font=fs, fill=(255, 255, 255))
    img.save(path)

def caption_png(words, hi, path):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(FONT_BOLD, 66)
    sp = d.textlength(" ", font=f)
    total = sum(d.textlength(w, font=f) for w in words) + sp * (len(words) - 1)
    x, y = (W - total) / 2, 1650
    for i, w in enumerate(words):
        d.text((x, y), w, font=f, fill=ACCENT2 if i == hi else (255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0))
        x += d.textlength(w, font=f) + sp
    layer.save(path)

# ---------------- 3. VOICE (Edge, same as the Kidzivora pipeline) ----------------
async def _tts(text, out):
    import edge_tts
    try:
        com = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE, boundary="WordBoundary")
    except TypeError:
        com = edge_tts.Communicate(text, VOICE, rate=VOICE_RATE)
    words = []
    with open(out, "wb") as f:
        async for ch in com.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                st = ch["offset"] / 1e7
                words.append((st, st + ch["duration"] / 1e7, ch["text"]))
    return words

def make_voice(text, out):
    with ThreadPoolExecutor() as ex:   # thread: Colab already runs an event loop
        return ex.submit(asyncio.run, _tts(text, out)).result()

def audio_len(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).strip())

# ---------------- 4. VIDEO ----------------
def scene_clip(frame, text, idx):
    mp3, clip = f"{OUT}/v{idx}.mp3", f"{OUT}/c{idx}.mp4"
    words = make_voice(text, mp3)
    dur = audio_len(mp3) + 0.45
    caps = []
    for g in range(0, len(words), 3):          # 3 words on screen, the spoken one in yellow
        grp = words[g:g + 3]
        for k, (st, en, w) in enumerate(grp):
            nxt = words[g + k + 1][0] if g + k + 1 < len(words) else dur
            cp = f"{OUT}/cap{idx}_{g + k}.png"
            caption_png([x[2] for x in grp], k, cp)
            caps.append((cp, st, nxt))
    inputs = ["-loop", "1", "-framerate", str(FPS), "-i", frame, "-i", mp3]
    for cp, _, _ in caps:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", cp]
    fc = f"[0:v]scale=w='{W}*(1+0.015*t/{dur:.2f})':h=-2:eval=frame,crop={W}:{H}[b0];"   # very slow push-in
    prev = "b0"
    for j, (_, t0, t1) in enumerate(caps):
        fc += f"[{prev}][{2 + j}:v]overlay=0:0:enable='between(t,{t0:.2f},{t1:.2f})'[b{j + 1}];"
        prev = f"b{j + 1}"
    fc += f"[{prev}]format=yuv420p[v];[1:a]aresample=44100,apad[a]"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "44100", "-ac", "2", clip])
    return clip

def get_music():
    for b in ("https://incompetech.com/music/royalty-free/mp3-royaltyfree/",
              "https://aux.incompetech.com/music/royalty-free/mp3-royaltyfree/"):
        try:
            r = requests.get(b + urllib.parse.quote("Wallpaper.mp3"), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200 and len(r.content) > 100000:
                p = f"{OUT}/music.mp3"; open(p, "wb").write(r.content); return p
        except Exception:
            pass
    return None

# ---------------- 5. AUTO TOPIC (no repeats) + YOUTUBE UPLOAD ----------------
def previous_titles():
    repo, tok = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN")
    if not repo: return []
    names = []
    for page in range(1, 11):
        try:
            rows = requests.get(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}", timeout=30,
                                headers={"Authorization": f"Bearer {tok}"} if tok else {}).json()
        except Exception:
            break
        if not isinstance(rows, list) or not rows: break
        names += [x.get("name", "") for x in rows if x.get("tag_name", "").startswith("tech-")]
        if len(rows) < 100: break
    return names

def auto_topic():
    kind = "SQL" if time.gmtime().tm_yday % 2 == 0 else "Python for data analysis (pandas or plain Python)"
    done = previous_titles()
    d = ask_ai(f"""Suggest ONE topic for a 30-40 second YouTube Short teaching {kind} to data analysts
(useful in real work or job interviews, e.g. joins, window functions, CTEs, GROUP BY tricks, pandas groupby, merge, pivot, string tricks).
It must be different from these earlier videos: {json.dumps(done[:200], ensure_ascii=False)}
Return ONLY valid JSON: {{"topic": "one line, max 15 words"}}""", lambda d: bool(str(d.get("topic", "")).strip()))
    return d["topic"].strip()

def upload_youtube(video, title, description, privacy):
    cid, csec, rtok = (os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "TECH_YT_REFRESH_TOKEN"))
    if not (cid and csec and rtok):
        print("YouTube secrets missing -> not uploading"); return None
    tok = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": cid, "client_secret": csec, "refresh_token": rtok, "grant_type": "refresh_token"})
    tok.raise_for_status()
    access = tok.json()["access_token"]
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "categoryId": "27",
                        "tags": ["sql", "python", "data analytics", "data analyst", "sql interview questions", "pandas", "shorts"]},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(video)
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                      data=json.dumps(meta), timeout=60)
    r.raise_for_status()
    with open(video, "rb") as f:
        up = requests.put(r.headers["Location"], data=f, timeout=900,
                          headers={"Authorization": f"Bearer {access}", "Content-Type": "video/mp4"})
    up.raise_for_status()
    vid = up.json()["id"]
    print(f"uploaded to YouTube ({privacy}): https://youtube.com/shorts/{vid}")
    return vid

# ---------------- RUN ----------------
if not TOPIC:
    print("0/4 picking a new topic...")
    TOPIC = auto_topic()
    print("  topic:", TOPIC)
print("1/4 writing the example + running the code...")
EX, RES, err = None, None, ""
for attempt in range(3):
    EX = make_example(TOPIC, err)
    try:
        RES = run_example(EX); break
    except Exception as e:
        err = str(e)[:500]; print(f"  code failed (try {attempt + 1}/3): {err[:120]}")
if RES is None:
    raise SystemExit("The AI could not write working code for this topic - try another topic.")
print(f"  title: {EX['title']}\n--- code ---\n{EX['code']}\n--- real output ---\n{result_as_text(RES)}")

print("2/4 writing the voice-over from the real output...")
NAR = make_narration(EX, RES)
print(json.dumps(NAR, indent=2, ensure_ascii=False))

print("3/4 drawing screens + voice...")
scenes = []
hook_frame(f"{OUT}/f_hook.png"); scenes.append((f"{OUT}/f_hook.png", NAR["hook"]))
if RES["input"] and NAR.get("table"):
    card_frame(f"Table: {RES['input']['name']}", table_img(RES["input"]["cols"], RES["input"]["rows"]), f"{OUT}/f_table.png")
    scenes.append((f"{OUT}/f_table.png", NAR["table"]))
card_frame("Query" if EX["kind"] == "sql" else "Code", code_img(EX["code"], EX["kind"]), f"{OUT}/f_code.png")
for line in NAR["code"][:3]:
    scenes.append((f"{OUT}/f_code.png", line))
out_img = table_img(RES["cols"], RES["rows"]) if RES["text"] is None else text_block_img(RES["text"])
card_frame("Output", out_img, f"{OUT}/f_out.png"); scenes.append((f"{OUT}/f_out.png", NAR["output"]))
takeaway_frame(NAR["takeaway"].replace("Follow for daily SQL and Python tips", "").strip(" .,-") or NAR["takeaway"], f"{OUT}/f_end.png")
scenes.append((f"{OUT}/f_end.png", NAR["takeaway"]))
clips = [scene_clip(fr, tx, i) for i, (fr, tx) in enumerate(scenes)]

print("4/4 joining + soft music...")
with open(f"{OUT}/list.txt", "w") as f:
    f.write("".join(f"file '{os.path.abspath(c)}'\n" for c in clips))
run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", f"{OUT}/list.txt", "-c", "copy", f"{OUT}/joined.mp4"])
final = f"{OUT}/sql_short.mp4"
music = get_music() if MUSIC_VOL > 0 else None
CREDIT = ""
if music:
    run(["ffmpeg", "-y", "-i", f"{OUT}/joined.mp4", "-stream_loop", "-1", "-i", music, "-filter_complex",
         f"[1:a]volume={MUSIC_VOL}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", final])
    CREDIT = ('Music: "Wallpaper" Kevin MacLeod (incompetech.com)\n'
              "Licensed under Creative Commons: By Attribution 4.0 License\nhttp://creativecommons.org/licenses/by/4.0/")
else:
    os.replace(f"{OUT}/joined.mp4", final)
print(f"DONE -> {final}  ({audio_len(final):.1f} s)")

TITLE = f"{EX['title']} #shorts"
DESC = (f"{NAR['hook']}\n\n{'Query' if EX['kind'] == 'sql' else 'Code'}:\n{EX['code']}\n\n"
        f"Output:\n{result_as_text(RES)}\n\n{NAR['takeaway']}\n\n"
        "#sql #python #dataanalytics #dataanalyst #shorts" + (f"\n\n{CREDIT}" if CREDIT else ""))
open(f"{OUT}/title.txt", "w", encoding="utf-8").write(EX["title"])
open(f"{OUT}/release_notes.txt", "w", encoding="utf-8").write(f"Topic: {TOPIC}\n\n{DESC}")
if os.environ.get("YT_UPLOAD", "").lower() in ("yes", "true", "1"):
    try:
        upload_youtube(final, TITLE, DESC, os.environ.get("YT_PRIVACY", "public") or "public")
    except Exception as e:
        print("YouTube upload failed (video is still saved):", str(e)[:300])
try:
    from IPython.display import Video, display
    display(Video(final, embed=True, width=320))
    from google.colab import files; files.download(final)
except Exception:
    pass
