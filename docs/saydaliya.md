# Night Pharmacy Finder: team brief

**One line:** at night, one tap shows the closest pharmacy that is open right now.

## Why this project

In Morocco, only "pharmacies de garde" are open at night, on weekends and on holidays. The list changes every day, and finding the closest one means scrolling lists and checking Google Maps one by one, usually when someone is sick. Our app answers one question: **"Which on-duty pharmacy is closest to me, right now?"**

## What we build (3 screens)

1. **Home:** a map and one big button, "Find nearest pharmacy now". Filters: All / Night / 24h.
2. **Result:** the closest pharmacy with distance, estimated time, Call, Navigate and WhatsApp share. Users can tap "It's open" or "It's closed". If it's closed, we show the next one.
3. **Coverage map:** green zones are within 3 km of an on-duty pharmacy, amber zones are not.

Mockup: *(paste the link here)*

## Tools, in simple words

| Tool | What it does for us |
|---|---|
| **PostGIS** | The database that understands maps. It finds the nearest pharmacy and builds the coverage zones. |
| **Kafka** | A reliable mailbox. Changes (new rota, "it's closed") are dropped in, and the app picks them up. Nobody waits for anybody. |
| **OpenStreetMap** | Free source of real pharmacies and roads. |

## Where Kafka fits

- **Duty rotas** come from different sources and change daily. They all go into one mailbox.
- **Confirmations** ("it's open" / "it's closed") can arrive in bursts at night. The mailbox absorbs them.
- Searching for the nearest pharmacy does **not** use Kafka. It asks the database directly, so it stays fast.

## How we split the work

We split by **feature**, not by tool, so everyone touches the database, Kafka and the screens.

There are three slices (A, B, C) and a shared Step 0. Each feature below says what it is, an example, and why we need it.

### Slice A: Who is on duty tonight?

*One-minute demo: send a rota message, and the pharmacy becomes on-duty on the map.*

**1. Load the real pharmacies**
- *What:* Download the list of all pharmacies in Casablanca from OpenStreetMap (a free map made by volunteers) and put them in our database with their name, address, phone and position on the map.
- *Example:* After this step, the database knows there is a pharmacy at a given street in Maarif, and exactly where it is.
- *Why:* Without a list of pharmacies, there is nothing to search.

**2. Apply the duty rota**
- *What:* Each night only some pharmacies are "on duty" (open at night). We receive that information as small messages like "Pharmacy X is on duty from tonight 8pm to tomorrow 8am", and the database marks that pharmacy as on duty.
- *Example:* You send one message, and the pharmacy turns green on the map.
- *Why:* This is what makes the app say "open now" rather than just "a pharmacy".

**3. Filters: All / Night / 24h**
- *What:* Three buttons on the home screen. "Night" shows pharmacies open at night, "24h" shows the ones open all day and night.
- *Example:* Tap "24h" and the map only keeps the 24h pharmacies.
- *Why:* People need different things depending on the hour.

**4. Rota simulator**
- *What:* A small script that sends fake rota messages by itself, as if the rota were changing.
- *Example:* You run it during the demo and pharmacies switch on and off on the map without anyone touching anything.
- *Why:* Real rota data is hard to get, and the demo needs something live to show.

### Slice B: Is it really open?

*One-minute demo: send "closed", and the status changes; the coverage zones update.*

**5. Confirmations ("It's open" / "It's closed")**
- *What:* Two buttons for users. If you go to a pharmacy and it is closed even though the list said open, you tell the app. The app remembers.
- *Example:* Someone taps "It's closed". The pharmacy is marked closed and the next user is not sent there.
- *Why:* Lists are sometimes wrong. People helping each other fixes that.

**6. "Confirmed 12 min ago" label**
- *What:* Next to each pharmacy, we show how recently someone confirmed it was open.
- *Example:* "Confirmed open 12 min ago" feels trustworthy. "Not confirmed recently" tells you to call first.
- *Why:* A confirmation from yesterday is useless. The label shows how fresh the information is.

**7. Coverage map**
- *What:* A map that shows which parts of the city have an open pharmacy within 3 km (green) and which don't (amber).
- *Example:* "38% of the area has no on-duty pharmacy within 3 km tonight."
- *Why:* It shows where people are poorly served at night. It's also the most original part of the project.

### Slice C: The closest one

*One-minute demo: press the button, get the closest pharmacy with a route.*

**8. Find the nearest pharmacy**
- *What:* The core feature. The app takes your position and asks the database "which on-duty pharmacies are closest?". It returns the 3 closest, the first one being the answer.
- *Example:* You press the big button and the app answers "Pharmacie Al Amal, 1.4 km".
- *Why:* This is the whole reason the project exists.

**9. Result card and route**
- *What:* The screen that shows the answer: name, address, distance, estimated drive time, and buttons to call, navigate or share. A line on the map connects you to the pharmacy.
- *Example:* You tap "Navigate" and Google Maps opens with the destination ready.
- *Why:* The answer is only useful if you can act on it in one tap.

**10. Speed test**
- *What:* We measure how fast the "nearest pharmacy" search is with and without a database speed-up (called an *index*, like the index at the back of a book). We use a large fake dataset so the difference is visible.
- *Example:* "Without the index: 400 ms. With the index: 2 ms."
- *Why:* It proves we understood the course, and it gives us one great number for the presentation.

**11. WhatsApp, languages and dark mode**
- *What:* A button to send the pharmacy to a family member on WhatsApp, a switch between French and Arabic, and a dark theme for night use.
- *Example:* You send "Pharmacie Al Amal, 1.4 km, [map link]" to your sister in one tap.
- *Why:* This is how people in Morocco would really use the app at night.

### Step 0 (all of us, first)

**12. Shared base**
- *What:* One setup that starts the database and the mailbox (Kafka) on everyone's computer, plus a file of about 20 fake pharmacies, plus a written agreement on what the messages look like.
- *Why:* So everyone can start working on day 1 without waiting for anyone else.

## Rules so nobody waits for anybody

1. **Step 0, all together:** one setup that runs the database and Kafka, a seed file of about 20 fake pharmacies, and an agreed format for the data (what a pharmacy and each message look like).
2. **A feature is done when we can demo it alone in one minute, using fake data.**
3. **Use fake data until real data arrives.** Don't wait for another slice.
4. **Cross-review:** every few days, review one change from someone else's slice, so we all learn the whole app.
5. **Announce database changes** before making them.
6. **If someone is late,** the others help them. We ship the whole app, not three separate parts.

## Biggest risk: the data

We need the real on-duty rota for at least one city (Casablanca). Slice A owns finding it, by scraping a public list or typing it in manually. Until then, we use fake data.

## Priority if time runs short

1. **Must:** nearest on-duty pharmacy, result card, map, filters.
2. **Should:** confirmations, coverage map, WhatsApp, French/Arabic.
3. **Stretch:** road-based travel time, large-scale analysis with Sedona, open dataset export.
