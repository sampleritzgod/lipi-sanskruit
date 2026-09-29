# Lipi-Sanskruit — SaaS Project Plan (v2)

## Product in one line

Upload a manuscript page (photo/PDF). The system reads the old handwritten script into modern Devanagari at **99% accuracy** and explains it in **Hindi and Sanskrit** (secondary languages: Gujarati, English), with citations from reference PDFs.

## Decisions made (29 Sep 2026)

| Question | Answer |
|---|---|
| Manuscript types | All: Jain (Prakrit/Old Gujarati), Sanskrit shastra, Hindi/Braj |
| Output languages | **Hindi + Sanskrit primary**; Gujarati, English secondary |
| Expert corrector | One person who corrects the readings by hand |
| Cloud vs offline | Both: cloud AI for best quality, our own model for low cost and privacy |
| Data volume | Many pages already scanned |
| Business | **SaaS** (multi-user, paid) |

## What "99% accuracy" means (defined precisely, so we can prove it)

- **Metric:** character error rate (CER) ≤ 1% on a **held-out test set** that the models never train on.
- It is reported **per difficulty class**:

| Page class | Machine-only target | With 1 human pass |
|---|---|---|
| Clear, well-preserved | ≤ 1% CER (99%) | ~99.9% |
| Average (faded, ink bleed) | ≤ 3% at first → ≤ 1% after training | 99%+ |
| Damaged (holes, stains, missing ink) | ≤ 8% | 99%+ on the visible text |

- Honest note: 99% on *every* page with no human review is not realistic on damaged manuscripts, where even experts disagree. The product therefore does two things:
  1. It gives a **confidence score for every akshara** and highlights anything uncertain.
  2. It offers a **"Verified" tier**, where uncertain lines go to a human reviewer. That tier guarantees 99%+.

## How we reach 99%: the data flywheel

Accuracy comes from *your own corrected data*, and the corrector is the engine of it.

```
 many scanned pages
        │
        ▼
 Machine reads (ensemble) ──► confidence per line
        │
        ▼
 Corrector reviews: LOWEST-confidence lines first (active learning)
        │
        ▼
 Corrected lines ──► training set grows ──► retrain model every N lines
        │                                        │
        └────────── better model ◄───────────────┘
```

- **Active learning:** the corrector never wastes time on lines the model already gets right. They only see the lines the model finds hard, and each correction teaches the model the most.
- **Data needed (estimate):** about 2,000 lines to beat the cloud AI alone, about 10,000 lines to approach 99% on average pages, and more for rare hands and scripts.
- **Corrector speed:** a good review UI makes one line take about 20–40 seconds, so 10,000 lines ≈ 60–110 hours of work. The UI speed matters as much as the model.

## Reading engine (ensemble)

| Component | Role |
|---|---|
| Vision LLMs (Claude, Gemini, GPT) + glyph reference sheet + few-shot | Strong from day 1; costs money per page |
| **Our fine-tuned HTR model** (TrOCR / Surya / Kraken, trained on corrector data + synthetic glyph data) | Cheap, private, gets best on *our* scripts over time |
| Sanskrit/Hindi language checker (Vidyut sandhi + morphology, MW/Apte dictionaries, Hindi lexicon, n-gram LM from GRETIL/DCS/Wikisource) | Catches impossible words |
| **Vote / merge step** | Aligns all readings per akshara; where they agree, confidence is high; where they disagree, the line is flagged |

Rule: the LLM must **never silently "fix"** text into a famous verse. The raw reading is always stored, and every change is shown as a diff.

## Understanding layer

- Scripts: modern Devanagari, Gujarati, IAST (`indic-transliteration`).
- Sanskrit: padaccheda (word split), sandhi-viccheda, vibhakti/lakara analysis (Vidyut / Sanskrit Heritage), anvaya, meaning in Hindi.
- Hindi/Braj: modern Hindi paraphrase + difficult-word glossary.
- **RAG over reference PDFs:** OCR legacy-font PDFs (Kruti Dev / Shree-Lipi text is garbage when extracted directly), embed with BGE-M3, and store in Postgres + pgvector. Every meaning cites *book + page*.
- Each user/organisation can upload its **own private reference library** (a SaaS feature).

## SaaS architecture

```
Browser (Next.js)
   │  upload, page viewer, line editor, results, billing
   ▼
API (FastAPI, Python) ── auth (Clerk) ── billing (Stripe / Razorpay for India)
   │
   ├── Postgres (Neon) + pgvector: users, orgs, documents, lines, corrections, embeddings
   ├── Object storage (Cloudflare R2 / S3): page images, PDFs
   ├── Job queue (Redis + worker): preprocess → read → correct → understand
   └── GPU inference (Modal / RunPod, serverless): our HTR model; cloud LLM APIs
```

- **Multi-tenant:** every table has an `org_id`, and customers' manuscripts are private and isolated.
- **Training consent:** customers opt in before their corrections are used to train the shared model. This protects trust and is important for temple/bhandar/library customers.
- **Model registry:** every model version is saved with its test-set CER, and a new version only ships if it beats the current one.
- **Cost control:** try our own model first and call the expensive LLMs only on low-confidence lines. Track the cost per page on a dashboard.

### Plans (draft)

| Plan | For | Includes |
|---|---|---|
| Free | Students | 20 pages/month, machine reading only |
| Scholar | Researchers | 500 pages/month, meanings + citations, own reference library |
| Institution | Bhandars, universities, libraries | Bulk upload, team review, private model fine-tune, export (TEI XML, PDF, Word) |
| Verified | Anyone | Human-reviewed 99%+ output, priced per page |

## Phases (each ends with proof: real numbers, not "looks good")

### Phase 0: Setup and data inventory (week 1)
- Re-export the 29 broken HEIC files. Put all scans in one place and log them in `data/inventory.csv` (script, language, era, condition).
- Monorepo: `apps/web` (Next.js), `services/api` (FastAPI), `ml/` (training, eval), `data/`.
- **Done when:** the inventory lists all pages with their difficulty class.

### Phase 1: Test set and baselines (weeks 1–2)
- The corrector transcribes 500 lines across all script types and difficulty classes. These lines are **locked away as the test set** and never used for training.
- Measure Tesseract, Surya, Google Vision, Claude, Gemini and GPT.
- **Done when:** `eval/baseline.md` has a CER table per tool × difficulty class.

### Phase 2: Glyph knowledge base (week 2)
- Digitise the lipi-book tables into `glyphs.json` + cropped variant images, and build the reference sheet (पृष्ठमात्रा, look-alikes, numerals, conjuncts).
- **Done when:** the full varnamala + barakhadi + conjuncts are in JSON.

### Phase 3: Reader v1 + correction tool (weeks 3–5), *the flywheel starts here*
- LLM ensemble + voting + confidence per akshara.
- **Internal review UI for the corrector:** line image above, editable text below, keyboard-only workflow, lowest-confidence lines first.
- **Done when:** the test-set CER beats the best baseline, and the corrector's speed is measured (lines per hour).

### Phase 4: Train our own model v1 (weeks 5–8)
- Training data: corrector lines + synthetic lines (glyph variants × GRETIL/Hindi text) + public datasets (IIIT-HW-Dev and others, license permitting).
- Fine-tune on a rented GPU, add the model to the ensemble, and retrain automatically every ~1,000 new lines.
- **Done when:** the ensemble with our model beats Reader v1 on the test set.

### Phase 5: Understanding + RAG (weeks 7–9, runs in parallel)
- Reference-PDF ingestion (with OCR fallback), Sanskrit analysis, Hindi meaning with citations.
- **Done when:** the corrector (or a Sanskrit expert) marks ≥ 90% of 50 sample verse explanations as correct.

### Phase 6: SaaS MVP (weeks 9–12)
- Auth, orgs, upload, job queue, results viewer, export, billing, usage limits.
- **Done when:** an outside test user signs up, uploads a PDF, pays and downloads the results without help.

### Phase 7: Reach 99% (ongoing)
- Keep the flywheel running, publish the test-set CER per model version, and add the Verified tier.
- **Done when:** the test-set CER is ≤ 1% on clear and average pages.

## Risks

- **Copyright (serious for SaaS):** the lipi book's tables and many reference PDFs are copyrighted. Internal study is fine, but **shipping them in a paid product needs permission** or our own re-drawn glyph charts. Public-domain dictionaries (Monier-Williams, Apte 1890) are safe.
- **One corrector = a bottleneck:** make the UI fast, use active learning, and later add a second reviewer. Two reviewers are also needed to measure human agreement, which is the real ceiling for "99%".
- **LLM cost at scale:** our own model must handle most lines by Phase 7.
- **LLM hallucination:** always keep the raw reading and show a diff.
- **Customer data privacy:** manuscripts can be sensitive, so use per-org isolation and opt-in training consent.

## Next step

Start Phase 0: set up the repo, fix the broken images, and create the inventory. Then the corrector begins the 500-line test set.
