# Archive

Files moved here on 2026-09-25 after a review found them unusable or misleading. They are kept for reference, not for use.

| Item | Why it was archived |
|---|---|
| `README.md`, `HANDOVER.md`, `FRONTEND_DEBUG.md` | Claim the system is "100% working" and "ready for production". It is not. The "Astro dev-server limitation" they describe does not exist. |
| `frontend/`, `docs/` | The search page calls `http://localhost:8002`, so the GitHub Pages site can only work for someone running the API on their own machine. The Pages workflow published the stale `frontend/dist/`, not `docs/`. |
| `.github/workflows/` | The daily scrape failed on every run from 2026-09-20 (`sentence-transformers` 2.2.2 is incompatible with the current `huggingface_hub`), and its Slack alert had no webhook. Both workflows are also disabled on GitHub. |
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `scripts/setup.sh` | Assume a separate Chroma server and environment variables that the code never reads. The code uses embedded Chroma in `./chroma_data`. |
| `chroma_data/` (local only, gitignored) | 1,635 entries from one listing page. Titles only (average 63 characters, 75% of entries are just the title), and every entry has the same URL, so no result links to its document. |

## `search-prototype/`

The scraper, processor, API, and config from the same prototype, archived when the repository became a website archiver template (see the main README). Known problems when archived:

- The scraper saves only the listing text for each item: no document URL and no document content. PDFs are not fetched.
- `LocalEmbedder` output is discarded; Chroma computes its own embeddings.
- The relevance score (`1 - distance/2`) overstates similarity.
- `requirements.txt` pins `sentence-transformers==2.2.2`, which fails with current `huggingface_hub`.
