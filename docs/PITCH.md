# Sonnabon, the five minutes

Slide content for the submission video. Every figure below is measured from this
repo and re-checked on 2026-09-09, except the two marked **SOURCE IT**.

The whole film turns on one sentence. Everything before it sets it up and
everything after it is proof:

> **Her best days are her worst days.**

---

## 1. Cold open

**On screen:** a counter at closing time. What is still sitting on it, and what
is not.

**Title:** *It is nine at night. She has been here since four.*

**Say:**
> A small bakery keeps a few cents on every euro it takes, and throws away
> roughly a tenth of what it makes. **SOURCE IT** Which means the two decisions
> that matter most, how much to bake and how much to order, are made last, from
> memory, by the most tired person in the building.

---

## 2. Meet Sarah

**On screen:** one person, one shop. No UI yet.

**Title:** *Sarah runs a pâtisserie. Nine products. Four people.*

**Say:**
> Sarah is good at the part she trained for. Nobody trained her for the rest.
> Every night she decides tomorrow's production for nine products from memory.
> Four suppliers each want their order by a different hour. And somewhere in
> October, Christmas is coming, and the flour for it needed ordering three weeks
> before she will think about it.

**The three burdens, as three lines:**

| | |
|---|---|
| **The time** | The planning and the ordering happen after close, tired, from memory |
| **The maths that never gets done** | How much to bake is a real calculation. No small shop does it, because there is no hour for it and nobody was taught which numbers matter |
| **The planning left too late** | Occasions arrive with no time to prepare. The market whose applications closed in August is simply missed |

---

## 3. What she has to work with

**On screen:** one receipt, held up, four seconds.

**Say:**
> This is everything the shop knows about itself. A pile of these. **149,384 of
> them** across **318 trading days**, and not one of them says what she should
> have baked.

---

## 4. The reversal ← the centre of the film

**On screen:** the sell-out chart. Let it sit.

**Title:** *Her best days are her worst days.*

**Say:**
> Here is a Sunday in August. Sixty tiramisu sold, nothing left on the shelf.
> In the till, that is a perfect day.
>
> The tray emptied at **12:51**. It stayed empty for **seven hours and nine
> minutes**. About **132 people** wanted one that day. Sixty got one. The other
> **72** looked at an empty tray and left, and took **€233** of margin with them.
>
> A till can only count what leaves the shelf. It has no way to count the people
> who wanted something that was not there. So the loss is not just invisible.
> **It is filed as a success.** And next year she bakes sixty again.

**Beat. Then:**
> Every forecast she could buy is trained on that file. Trained on sales, a
> forecast learns to under-bake, and it gets worse every year: less made, sells
> out sooner, records an even lower number.

---

## 5. This is Sonnabon

**On screen:** the chef, the name, and one line.

**Title:** *The operations and planning manager a small bakery cannot afford.*

**Say:**
> Sarah cannot hire an operations manager and a planner. So she is both, at nine
> at night, from memory. Sonnabon is that hire.
>
> You brief it once, the way you would a manager on their first day. After that
> it runs the production side without being asked.

**What it does, two halves:**

**Operations.** Reads the till. Works out what to make tomorrow, product by
product, from the statistics she has no evening to sit down with.

**Planning.** Holds the calendar. Works backwards from each occasion to the day
the ingredients have to be ordered. Hands each person their list, tracks what
came back, and looks outward for the markets worth taking a stall at.

**And the part that matters most:** it emails her **only** when a decision needs
a person.

---

## 6. What it takes off her

**On screen:** four rows, plain.

| Every | It does | So that |
|---|---|---|
| Close of trade | Reads the day and works out what actually ran out | The number in the till stops being the number she plans on |
| Close of trade | Decides tomorrow's production, product by product | The decision is made on data, not on how tired she is |
| Supplier cutoff | Works back to ingredients and raises the orders | Four suppliers, four deadlines, none of them hers to remember |
| Weeks ahead | Holds the calendar and the run-up to each occasion | Christmas arrives with the flour already ordered |

**Say:**
> The last row is the one that matters most, because it is the one that never
> happens. There is no evening left for it.

---

## 7. How it does the thing a till cannot

**On screen:** the two curves.

**Title:** *The timestamps are the way out.*

**Say:**
> A product that stops selling dead while everything else keeps going has run
> out. That is provable from data she already has.
>
> Sonnabon learns each product's normal shape through the day, from the days it
> did not run out. Then on a day it did, it works out how far through that shape
> it got, and scales up. Sixty becomes a hundred and thirty-two.
>
> Everything downstream reads that corrected history. Never the raw sales.

**How well it works, against demand that is genuinely known:**

| | |
|---|---|
| Sell-out detection | **91%** precision, 80% recall, across 807 real sell-outs |
| Demand estimate | **3.0%** median error, within 20% on 99% of 649 scored days |
| A year of lost margin | Estimated **€27,618** against a true **€29,566** |

**Say, if asked about the data:**
> The shop is generated, and that is the method, not an apology. **No real till
> can tell you how many people wanted something and left**, so no real dataset
> can score this. Ours can, because we generated the demand first and then
> served it out of a limited tray.

---

## 8. It measures her shop, not a table

**On screen:** the Halloween card, 1.91x.

**Title:** *Every number it quotes comes from her own tills.*

**Say:**
> Halloween is fifty-five days away. Most software would tell her occasions lift
> sales by some number a consultant typed once.
>
> Sonnabon measured hers. Cinnamon roll, glazed donut, chocolate chip cookie,
> **1.91 times, last year, in this shop.**
>
> And here is why that is not a small detail. Measured off the raw till,
> Christmas looks like a **1.5x** week. Measured off what people actually
> wanted, it is **3.5x**. A shop planning Christmas from its own till
> under-bakes by more than half, and the till reports a triumph.

---

## 9. The work goes to people

**On screen:** the board.

**Say:**
> A decision that stays in a report is not a decision. Sonnabon turns the plan
> into tickets and splits them by who starts when.
>
> Sarah's own column is **empty**, on purpose. Work landing back on the owner is
> the thing this exists to stop.
>
> Whoever is on the counter gets one job: confirm what ran out. Sonnabon
> inferred it from the timestamps and says so. Only somebody standing there can
> settle it, and it reads the answer back: a confirmed sell-out is a fact it can
> lean on, an unconfirmed one is still its own guess, and it knows the
> difference when it speaks.

---

## 10. It runs the day on its own ← the autonomy shot

**On screen:** press **Start the till**. Then stop talking and let it run.

**Say, over the top:**
> Nobody is typing. That is the till selling, one bill at a time, into the same
> file the agent reads. Twelve hours in three minutes.
>
> The bakers finish their trays and the board ticks itself. Near close, the
> counter confirms what ran out. And at close of trade **it wakes up on its own**,
> reads the day, plans tomorrow, and decides whether Sarah needs to hear about
> it.

**On screen:** the diary filling in.

---

## 11. The restraint is the product

**On screen:** the diary, showing the quiet nights.

**Title:** *It reached her 8 nights out of 30.*

**Say:**
> An agent that emails you every night gets filtered within a week. An agent
> that never emails you is not trusted with anything.
>
> Sonnabon wakes every close of trade. Over thirty nights it reached the owner
> **eight times** and handled the other **twenty-two alone**. A night earns an
> email by being unusual for **this** shop, not by clearing a fixed number every
> shop clears most days. And a late task is raised once, not once a night.
>
> That ratio is the product, and it is on the page rather than in a sentence.

---

## 12. Does it actually do better

**On screen:** the counterfactual table.

|  | waste | lost sales | total |
|---|---|---|---|
| The shop, as it plans today | €9,912 | €8,321 | €18,233 |
| The shop, with Sonnabon | €12,579 | **€3,690** | **€16,269** |

**Say:**
> A hundred and twenty days, replayed, both plans priced against demand we
> actually know.
>
> Lost sales fall by **fifty-six percent**. Waste goes **up**, and that is
> correct: it buys availability with flour. Net it saves **€1,964** over four
> months, about **€5,000 a year**, and it is better on **65 days out of 120**.
>
> Running out costs more than binning does. Most owners believe the opposite,
> and that single inversion is what the maths is for.

---

## 13. How it is built

**On screen:** your architecture diagram.

**Say:**
> One agent on the Strands SDK. Fifteen tools. Its limits are not written into a
> prompt, because a prompt is a request and a model can talk itself out of a
> request. They are hooks inside the SDK's own loop that cancel the run: spend,
> looping, and irreversible actions.
>
> The last one matters most. Because the count comes from the tool about to run,
> **"did it email the owner?" is answered by the invocation, not by the model's
> closing paragraph.** An agent that says it sent something and did not is
> caught.

---

## 14. Close

**On screen:** the shop again. Not the software.

**Say:**
> Sarah did not get an analytics dashboard. She got the hour back, and the two
> decisions that were being made from memory are now made from her own data.
>
> It runs every night. It reaches her twice a month. It costs less than one
> unsold cake a week.
>
> **That ratio is the product.**

---

## Numbers, all in one place

Measured from this repo, 2026-09-09.

| Figure | Value |
|---|---|
| Bills | 149,384 across 318 trading days |
| Products | 9 |
| Real sell-outs in the year | 807 |
| Detection | 91% precision, 80% recall |
| Demand estimate | 3.0% median error, within 20% on 99% of 649 days |
| Year of lost margin | est. €27,618 vs true €29,566 |
| Hero day, Tiramisu 2026-08-16 | 60 sold, ~132 wanted, out 12:51, empty 7h 09m, 72 people, €233 |
| Halloween lift | till 1.31x, corrected **1.91x** |
| Christmas lift | till 1.49x, corrected **3.49x** |
| Counterfactual, 120 days | lost sales €8,321 → €3,690, net saved €1,964 (10.8%), better on 65/120 |
| Annualised | ~€5,000 |
| Restraint | speaks 8 nights in 30 |
| Build | 15 tools, 70 tests |

**SOURCE IT before using:** the opening claim about bakery margins and waste. It
is not measured here and a judge may check it. Either find a citation or cut it
and open on Sarah directly, which loses nothing.

---

## What to cut if you run long

- Slide 3, the receipt. Fold the number into slide 2.
- Slide 6, the four duties table. Slide 5 already says it.
- Slide 13, the build. Only if you must, and never before slide 10.

**Never cut:** slide 4 (the reversal), slide 10 (the autonomy shot), slide 11
(the restraint). Those three are the film.
