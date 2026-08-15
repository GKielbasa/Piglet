---
name: lesson-materials
description: Turn one course lesson transcript into the two files its work starts from — the knowledge base note and the task file.
disable-model-invocation: true
---

# Lesson materials

One transcript in `_teoria/`, two files out. Written **in Polish** — both destinations are the
exemptions named in `CLAUDE.md` section 0.

| File | Holds |
|---|---|
| `_knowledgeBase/{python,agents,workflow}/<sXXeYY>-<temat>.md` | what the lesson teaches, stripped of the course |
| `_tasks/<sXXeYY>-<nazwa>.md` | the task reduced to requirements, plus the **core** it exists to teach |

`_knowledgeBase/workflow/knowledgeBaseScope.md` is the authority on which of the two a given
sentence belongs to. Read it once per run rather than working from memory of it.

The author reads the lesson themselves. These files are what they read *against*, so the note
is judged by whether it is worth rereading in two years — in another job, with this repository
gone.

## 1. Read the whole transcript

A lesson runs 30–70 KB and `Read` truncates around 25k tokens, so a single call returns a
prefix and says so. The task statement lives at the **end**, under `## Zadanie`, after the
story section.

**Done when:** the line count read equals the file's line count, and the answer format the
platform expects is in front of you.

## 2. Decide the section list before writing a sentence

An **extract** keeps what changes a decision. A **summary** keeps everything, shorter. Only
the first is worth rereading, and the second is what you get by default.

The failure mode has one recognisable shape — **mirroring**: the note's section list matches
the lesson's own headings, in the lesson's order, one for one. That is transcription with
better typography, and it is invisible while writing because every individual sentence is true.

Sort every candidate topic into exactly one of three verdicts:

| Verdict | What it earns |
|---|---|
| **changes a decision** | full technical depth — names, numbers, exact error strings, thinking tools kept verbatim |
| **worth knowing it exists** | one paragraph, no table, no example |
| **already written above** | out |

Then merge: two sections arguing one idea become one section. Anything the lesson demonstrates
with a walked-through example gets the conclusion, not the walk-through.

**Done when:** the list exists as text, its length differs from the lesson's heading count, and
every entry carries its verdict.

## 3. Write the note

```
# SXXEYY — <temat lekcji>

> **Zasada jednym zdaniem:** <the one sentence the rest follows from>

---

## 1. <sekcja>
...

## Źródła
- `_teoria/<plik>.md`
- <links the lesson gives: papers, provider docs, example directories>
```

**Depth is not the thing being cut.** Prose is. A rule the lesson states in five sentences
becomes one sentence carrying all five facts — never four facts and a smoother read. Keep every
proper noun, every number, every exact string a reader could grep for.

Mark with `[stan RRRR-MM]` any fact that is a snapshot of the market: per-vendor capabilities,
numeric heuristics, "currently only X supports Y", "the current recommendation is". Leave
unmarked what holds regardless of vendor and year.

**Done when:** the file exists, and every `[stan …]` marker sits on a fact that could plausibly
be false in two years.

## 4. Write the task file

The task statement reduced to requirements: input, criteria, output shape with a JSON example,
the hints the statement itself gives, and what is genuinely undecided.

Two sections carry their weight beyond this task:

**`## Rdzeń — co z tego zostaje w agencie`**, placed directly after the goal. The generic
problem the task illustrates (`CLAUDE.md` section 6), then a table: what gets built, which
module it lands in, and what it is worth **outside** this task. Name explicitly what stays
course-specific and never leaves `application/`.

**`## Otwarte, do rozstrzygnięcia przed implementacją`**, last. Genuine ambiguities in the
statement — a threshold it never gives, a response shape nobody has seen yet, a type the
example does not pin down. Each one phrased so the author can rule on it in a sentence.

Facts about the repository's current state belong here too, and they are **checked, not
assumed**: whether the previous task's output survived anywhere, whether an input is still
cached. Run the check, then write what it returned.

**Done when:** the file exists and every open question is one the author could answer without
opening the code.

## 5. Verify before reporting

Run these and paste what they return — `CLAUDE.md` section 12 wants the output of a run, not a
claim about it.

```bash
# The tripwire. Under a third of the lesson's word count needs no defence;
# over it, name in the report which sections justify the weight.
wc -w _teoria/<lekcja>.md _knowledgeBase/<dzial>/<plik>.md

# Repetition, which is invisible while writing. For each phrase the note
# bolds as a conclusion, one hit is right and two is a section to merge.
grep -c "<fraza>" _knowledgeBase/<dzial>/<plik>.md

# The scope rule, mechanically. Both must come back empty.
grep -nE "hub\.ag3nts|apikey|FLG:|/verify" _knowledgeBase/<dzial>/<plik>.md
grep -n "piglet" _knowledgeBase/<dzial>/<plik>.md
```

Add the note's row to `_knowledgeBase/README.md` — a file missing from that index is a file
nobody finds.

**Done when:** both greps came back empty, the ratio has been stated as a number, and the index
row is in place.

## 6. Report, and hand back the two decisions that are the author's

Lead with the numbers: lesson word count, note word count, the ratio, and how many sections the
lesson had against how many the note has.

Then hand over, as proposals rather than as writes:

- **the core**, for acceptance — `CLAUDE.md` section 13 step 2 makes it the author's call, and
  everything built afterwards inherits it;
- **the `docs/COURSE_MAP.md` row** it implies, written out ready to paste.

A note for `_knowledgeBase/agents/skills/` is **not** part of this run. That one is written
after the capability exists and has been used, the way `taxonomyClassification.md` was.

**The run ends here, with the files written and the two proposals made.** Extracting the core
is step 2 of the workflow in `CLAUDE.md` section 13 and plan mode is step 5; three steps
belonging to the author sit between them, starting with reading what was just written. Moving
straight into a plan skips the reason the materials were produced.

**Done when:** the numbers are reported, the core and the COURSE_MAP row are on the table as
text, and nothing else has been written or planned.
