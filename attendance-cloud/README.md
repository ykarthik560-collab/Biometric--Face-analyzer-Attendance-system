# Attendance System — Cloud Version

Four pages, one server, and this time a real deployment path so it's a
link you can open on your phone, share with anyone, and never touch a
terminal for again.

- `/scanner` — camera check-in (passcode-gated — see below)
- `/dashboard` — teacher's live view, session controls, sets the passcode
- `/portal` — attendance % across completed sessions
- `/enroll` — add a new person by uploading their photo + name, right
  from the browser

## Testing it locally first (optional, but recommended once)

```
python server.py
```
Same as every version before — confirms everything still works before
you put it online.

## Getting the real link — no terminal, ever

**Step 1 — Get this code onto GitHub, without git commands.**
Install **GitHub Desktop** (github.com/apps/desktop) — it's a normal app
with buttons, not a terminal. Sign in with (or create) a GitHub account,
create a new repository from within the app, point it at this folder,
and click **"Commit"** then **"Publish repository."** That's it — your
code is now on GitHub.

**Step 2 — Create a free Render account.**
Go to render.com, click **"Get Started"**, and sign up using your GitHub
account (one click, no separate password to remember).

**Step 3 — Create the web service.**
On Render's dashboard: **New → Web Service**. Pick the GitHub repo you
just published. Render will detect the `render.yaml` file in this folder
and fill in the settings automatically — if it asks anyway, the start
command is `python server.py`. Choose the **Free** plan. Click **Create
Web Service**.

**Step 4 — Wait, then open your link.**
The first deploy takes a couple of minutes. When it's done, Render shows
you a URL like `https://attendance-system-xyz.onrender.com` — that's
your real, permanent link. Add `/scanner`, `/dashboard`, `/portal`, or
`/enroll` to the end of it, share it with anyone, open it on your phone —
it all just works, camera included, since Render gives you HTTPS
automatically.

**Updating it later:** make changes locally, then in GitHub Desktop click
**Commit** and **Push** — Render redeploys automatically within a minute
or two. Still no terminal, ever.

## Two honest limitations of the free tier

- **It falls asleep.** After about 15 minutes with no visitors, Render's
  free tier spins the service down. The next visit takes 30-60 seconds to
  wake back up — normal, not broken. Worth doing a "wake-up" visit a
  couple of minutes before you actually present.
- **Storage resets on redeploy.** Anyone enrolled through `/enroll`, and
  all attendance history, lives in files that get wiped every time you
  push new code (free tier disk isn't persistent). Fine for a demo;
  if this becomes something you run for real over a whole semester,
  the fix later is a proper database or Render's paid persistent disk —
  not needed right now.

## The passcode (why the scanner isn't fully open)

Making the scanner a public link means, technically, anyone anywhere
could open it and try to check themselves in — which defeats the whole
point of an anti-proxy attendance system. The dashboard has a **Scanner
Passcode** field: set it to something you announce in class that day
(changeable anytime), and the scanner won't unlock without it. Leave it
blank and the scanner is fully open — your call.

## Adding people through the browser

Go to `/enroll`, type a name, choose a clear front-facing photo, hit
**Add to Roster**. They're recognized on the scanner immediately — no
code edits, no redeploying, nothing for you to touch.

## Still not built

- No individual login on the portal — everyone's percentage is visible
  to anyone with the link.
- No timetable/per-subject awareness — one subject label
  (`SUBJECT_LABEL` in `server.py`), not multiple subjects.
- No ID card / second factor — face-only, as decided earlier.
