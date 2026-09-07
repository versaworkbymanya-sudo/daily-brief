# Daily Brief

Ek static news dashboard. Koi login nahi, koi server nahi, koi API key nahi.
Din mein do baar khud update hota hai. Kisi bhi device pe khulta hai.

## Setup (ek baar, ~10 minute)

1. GitHub pe naya **public** repo banao, naam `daily-brief`
2. Ye saari files usme upload kar do (drag and drop chalega)
3. Repo mein **Settings → Pages** kholo
4. **Source** ko `GitHub Actions` set karo
5. **Actions** tab pe jao → `Build daily brief` → **Run workflow**
6. 2 minute baad page live: `https://<tumhara-username>.github.io/daily-brief/`

Us URL ko phone pe bookmark kar lo. Bas.

## Kab update hota hai

Roz subah 7 baje aur shaam 7 baje IST. Badalna ho to `.github/workflows/build.yml`
mein cron time change kar do (wo UTC mein hai, IST se 5:30 kam).

Turant chahiye to Actions tab se "Run workflow" daba do.

## Sources badalne hain

`feeds.json` edit karo. Format:

```json
"Section ka naam": [
  ["Source ka naam", "https://feed-ka-url"]
]
```

Naya section banane ke liye bas nayi key add kar do. Page apne aap adjust ho jayega.

## Settings

`build.py` ke upar:

- `MAX_AGE_HOURS` — 36. Isse purani news drop ho jaati hai
- `MAX_PER_SECTION` — 22. Har section mein max itne items

## Local pe chalana

```bash
pip install -r requirements.txt
python build.py
open docs/index.html
```

## Kya karta hai

- 26 feeds se parallel mein news uthata hai
- Duplicate hatata hai (link se aur headline match se)
- Ek hi khabar agar 3 jagah hai to ek dikhata hai, "+2 more" ke saath
- 36 ghante se purani news hata deta hai
- Section-wise group karke ek page bana deta hai

Koi feed down ho to page phir bhi banta hai, neeche note aa jaata hai.
