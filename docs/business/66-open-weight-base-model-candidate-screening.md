# روناس — غربال مقدماتی مدل‌های پایه Open-Weight برای هوش اختصاصی | Candidate Screening 66

**Status: NON-BINDING BUSINESS RESEARCH / MODEL SHORTLIST FOR EVIDENCE REVIEW / NO MODEL SELECTED**  
**Date of public-source screening:** 2026-10-09  
**Binding decisions:** [RON-DEC-027 and RON-DEC-028](04-decisions-and-open-questions.md): AI wholly Ronas-controlled and internally operated; **Option B APPROVED** (properly licensed Open-Weight base + completely internal Ronas-specific fine-tuning), initial rights-cleared dataset, independent evaluation, Candidate only until explicit human promotion.  
**NOT authorized:** selecting an exact model/license version, downloading/training weights, Technical architecture, stack/algorithm/LoRA, any software Code, API, operational data ingestion, Stage, Production or any Business Gate PASS.  
**Current gates:** [Domestic #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2), [Export #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3), [Finance #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4) **OPEN**; [PR #1](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1) Draft/Open/Unmerged; PR #6 HOLD, PR #8 nonbinding Technical Discovery.  
**Evidence limitations:** Official publisher/model repository documentation is **initial source confirmation only**, not Ronas' legal clearance, agricultural evaluation, hardware benchmark or actual reproduction of vendor tests.

## ۱. Why these candidates / comparison basis

- The user explicitly approved **Open-Weight licensed base + self-hosted fine-tuning** with RON-DEC-028, **not** a named base model.
- Ronas includes independent **D0 noncommercial general education Domestic** and **E0 product–destination research Export** *Business packet preparation*, neither an approved first AI Training Task nor an operating scope. Household personalized agronomy (D1) and image-based observations require separate rights/scientific/Business gate; actual Export lead/contracts/payment likewise out of E0.
- Candidate screen emphasizes license terms, verifiable public weights, internal runtime/training feasibility, Persian capability needing external **Ronas-controlled validation**, later visual potential, scientific reliability and rights segregation. No weighted scoring, “winner,” benchmark performance or model size decision is asserted.

## ۲. Concrete candidates (Publisher Claims ≠ Validated Ronas Capability)

| Candidate | Publisher / specific canonical source | Officially visible characteristics | License display / actual rights | Business screening status |
| --- | --- | --- | --- | --- |
| **Gemma 4 12B instruction-tuned** | Google DeepMind; [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4); [official HF model](https://huggingface.co/google/gemma-4-12B-it); [Gemma 4 Apache text](https://ai.google.dev/gemma/apache_2) | ~11.95B; text, image, audio inputs; provider states 140+ pre-training languages (not Ronas Persian benchmark); self-hosted inference and fine-tuning documented, including [Google tuning guide](https://developers.googleblog.com/gemma-4-12b-the-developer-guide/) | Official Gemma **4** model card and the HF model state **Apache-2.0**; **this is not a blanket conclusion for older Gemma generations**. Exact model revision, notices, component dependencies, deployment/redistribution terms and legal fitness for Ronas **NOT VERIFIED** | **CANDIDATE / NOT SELECTED** |
| **Qwen3.5 9B post-trained** | Qwen; [official HF model](https://huggingface.co/Qwen/Qwen3.5-9B) and [Files](https://huggingface.co/Qwen/Qwen3.5-9B/tree/main) | 9B text + image input; official card claims 201 languages/dialects and shows published local inference paths; **no Ronas agricultural/Persian or training benchmark**; adaptation compatibility/accuracy must be checked | Official HF declares **Apache-2.0** and includes LICENSE; exact revision, file/derivative obligations, availability, downstream dependencies and legal-use fitness **NOT VERIFIED** | **CANDIDATE / NOT SELECTED** |
| **Qwen3 8B text-only comparator** | Qwen; [official HF model](https://huggingface.co/Qwen/Qwen3-8B); [Qwen3 publisher language announcement](https://qwenlm.github.io/blog/qwen3/) | 8B text-generation model only; Qwen3 announcement explicitly lists **Persian** among 119 supported languages/dialects; no image-input claim for this exact model; no demonstration of Persian agronomy correctness | Official HF declares **Apache-2.0**; real revision and compliance still require checking | **TEXT BASELINE CANDIDATE / NOT SELECTED** |

**Important:** Both Gemma 4 and Qwen3.5 model families are described as multilingual by their publishers. The lists “140+” and “201” count different defined language/dialect sets and **are not comparable measurements of quality in Persian**. Qwen3 explicitly lists Persian, but that does not prove Qwen3.5 9B's expected scores. General model benchmarks and publisher presentations cannot substitute for a held-out evaluation on legitimate Ronas scenarios. Image capability ≠ ability to validate plant disease, food safety, market product quality or legal compliance.

## ۳. License and sovereignty examination — blocking evidence

- **Open-Weight ≠ public domain/transfer of base-weights ownership to Ronas.** For each specific candidate, retain publisher, exact repository/commit or release, obtained LICENSE/NOTICE/model card, restrictions and amendment record.
- Examine obligations for **download, local reproduction, modification/fine-tuning, internal commercial use, serving users, derivative weights/adapters, redistribution or off-site deployments**, third-party code/datasets and applicable law. **Apache-2.0** is declared at source for these concrete versions; this is preliminary classification, not completed Ronas legal sign-off. [Apache 2.0 from Google Gemma 4](https://ai.google.dev/gemma/apache_2).
- Confirm lawful access and commercial availability for intended hosting jurisdiction, legal entity and delivery pattern **with real evidence**; do not extrapolate from model repository access.
- Sovereignty means **no operational training or inference reliance on external AI APIs**; downloading permitted base weights as a controlled initial acquisition is conceptually distinct from sending Ronas operational data to a third-party provider. Any allowed future artifact download is separately gated. No specific endpoint/runtime architecture, model host or vendor is chosen.
- Publicly accessible FAO/AGROVOC/NASA POWER/FAOSTAT/Comtrade pages are **not** thereby a rights-cleared model-training corpus. See [source rights screening 62](62-d0-e0-official-source-screening-and-usage-rights.md) and [dataset evidence 65](65-initial-ai-dataset-and-controlled-learning-evidence-blueprint.md).

## ۴. Business comparison questions before any final recommendation

| Dimension | Evidence to demand later / no invented threshold |
| --- | --- |
| **Legal rights** | Actual version-pinned license and notice inventory, derivative obligations, commercial/self-hosted use and authorized legal review |
| **Persian and local agronomy** | Independently prepared Persian questions and field terminology, Iranian cultivation/region/weather relevance, explicit source grounding, human expert judgments |
| **D0 general education** | Correctness of general learning content, differentiation from individualized cultivation advice, uncertainty/abstention in risky cases, citation reliability |
| **E0 export research** | Correct handling of product–destination / HS / year / partner / unit, provenance and differences across authoritative sources, distinguishing opportunity lead from buyer/contract and not inventing market figures |
| **D1 visual future (separate gate)** | Image validity, ambiguous photos, provenance/consent and expert decision; **not** automatically activated by multimedia model support |
| **Robustness** | Factual mistakes, conflicting/obsolete data, unknown/unsupported cases, hallucinated sources, bilingual terms, adversarial requests, off-topic leakage |
| **Controlled learning** | Ability to train on licensed, expert-reviewed task examples; versioned lineage and **independent nonoverlapping evaluation**; artifact governance and human Promotion, no background auto-deploy |
| **Internal economics** | Model checkpoint/storage and runtime/fine-tuning benchmarks on **real** proposed hosting hardware; support, licensing, staffing and energy/cost evidence, not guessed VRAM, GPU quantities or performance |
| **Two-engine boundary** | Domestic household data and Export supplier/contracts never pooled or reused without independent explicit rights and lawful scope |

**Evidence preparation only (no training):** legal candidate dossier for each, documented benchmark protocol proposal (without execution), expert reviewer/authority evidence request, approved task definition **after owner direction**, authenticated initial training/evaluation data permits. The same benchmark/evaluation corpus and conditions should be used fairly across candidate families only once authorized, preserving multimodal task differences.

## ۵. Recommendation limited to research stage (NOT owner approval)

Keep **Gemma 4 12B** and **Qwen3.5 9B** as the two principal *multimodal* candidates for further evidence; keep **Qwen3 8B** as a *text-only comparator* for the D0/E0 discussion. No basis currently proves one wins: strengths claimed by publishers in general reasoning or multilingual coverage do not validate agronomic advice, Persian safety, internal fine-tuning cost or cross-engine rights. A lighter text-only solution could be sufficient if the **first** approved task is only D0 or E0 text; a multimodal model may have future potential but D1 and photo supervision are outside the current limited scopes. **Do not infer first Task from model choice or vice versa.**

**Decision boundary:** RON-DEC-028 **remains approved** but does **not** silently create a RON-DEC-029 model selection. The current decision-maker needs not choose among models at this stage; gather rigorous rights and task-specific benchmark evidence first, then request an explicit, version-specific owner decision after relevant Business/Technical gates. No dataset, training run, implementation or API is authorized here.

**Final state:** PUBLIC SOURCE SCREENING RECORDED / 3 CANDIDATES / NO WINNER, NO MODEL FAMILY APPROVAL / RIGHTS NOT CLEARED / FIRST TASK OPEN / BUSINESS GATES #2/#3/#4 OPEN / TECHNICAL & CODE BLOCKED.
