---
name: literature-search
description: "Find, retrieve and verify scientific literature on the internet: papers, accepted manuscripts, bibliographic data, and the exact wording of claims. Use it whenever a claim about published chemical-kinetics or combustion work must be checked or sourced, when a reference must be completed or verified, or when looking for literature relevant to a KiMecO development (master equation, MESS, AutoMech, non-Boltzmann or prompt kinetics, combustion chemistry)."
---
# Literature search and verification

Use `WebSearch` to find sources and `WebFetch` to read them.

## Where to look, in order of preference
1. **Primary text of the work.**
   - Publisher pages are often paywalled: the abstract is readable, the full text usually is not.
   - The accepted manuscript on **OSTI.gov** (`https://www.osti.gov/search/semantic:<title words>`, or `https://www.osti.gov/pages/biblio/<id>`). DOE-funded work, e.g. Argonne or Sandia, is usually there.
   - arXiv or ChemRxiv preprints.
   - Institutional repositories.
2. **Bibliographic metadata.** Crossref:
   - search: `https://api.crossref.org/works?query.bibliographic=<title+authors>&rows=3`
   - by DOI: `https://api.crossref.org/works/<doi>`
   
   Use Crossref to verify authors, journal, volume, pages, year and DOI.
3. **Code and data** for methods implemented in software. For AutoMech that is `https://github.com/Auto-Mech/{mechanalyzer,mechdriver,autoio,autochem}`. Cite the file and line, or the tag.
4. **Other sources.** Reviews and textbooks, only to support background statements.

## Rules
- **Never fabricate** a reference, quotation, number or equation. If a claim cannot be checked against a source you actually read, label it **UNVERIFIED** and say what you tried.
- **Quote exactly**, and give the page or section.
- **Check equations on the rendered PDF.** Text extraction garbles equations: in this project the c(E) factor of Eq. 6 of Pratali Maffei et al. 2023 was lost in extraction.
- **Separate what the paper says from what you infer.** Never attribute an inference to a paper.
- **When citing, give** authors, title, journal, volume, pages, year, DOI, and the URL actually read.
- **Keep fetched material out of the repository.** Save PDFs or text only under the session scratchpad.
- **Prefer the version of record.** When only an accepted manuscript is available, say so.

## Output
Put the findings in your review file:
- a list of sources, each marked VERIFIED (read) or UNVERIFIED;
- for each claim checked: the claim, the source and location, and the verdict (correct / incorrect, with the correction / unverifiable).
