# `sites.yaml`: the control file

`sites.yaml` is the only file you need to edit. It has three sections:

```yaml
dashboard:      # which dashboard formats to build (optional)
  ...
defaults:       # settings for every site (optional)
  ...
sites:          # the sites to capture
  - url: ...
```

Committing a change to `sites.yaml` starts the **Archive sites** workflow, which captures any new sites straight away. The **Test** workflow checks the file at the same time; if it has a mistake, that check fails with a message saying what's wrong.

## `sites:`

Each entry needs a `url`. Everything else is optional.

```yaml
sites:
  - url: https://www.example.gov.au

  - url: https://www.example.gov.au/publications/
    name: example-publications
    scope: prefix
    schedule: monthly
    site_files: true

  - url: https://blog.example.org
    exclude:
      - /tag/
      - \?replytocom=
```

YAML is fussy about spacing: each site starts with `- ` (dash, space), and its settings line up two spaces further in. Lines starting with `#` are comments.

## Settings

Set any of these under `defaults:` to apply them to every site, or on one site to override the default for that site.

### What to capture

| Setting | Default | Values | Meaning |
|---|---|---|---|
| `url` | (required) | a web address | Where the crawl starts. Redirects are followed. |
| `name` | made from the URL | letters, numbers, dashes | Short name used in release tags, titles, and page-list addresses. Set it when two sites would otherwise get the same name, or to keep names short. Changing it later starts a new capture history. |
| `scope` | `host` | `host`, `domain`, `prefix` | Which links the crawl follows. `host`: only this host; `www.example.org` and `example.org` count as the same. `domain`: also subdomains such as `blog.example.org`. `prefix`: only addresses under the starting path; with `https://example.org/publications/`, only `/publications/...`. |
| `exclude` | none | list of patterns | Skip addresses matching any of these [regular expressions](https://regex101.com/). Examples: `/tag/`, `/search`, `\?replytocom=`. A `?` or `.` needs a `\` in front. |
| `page_limit` | `0` | a number | Stop after this many pages; `0` means no limit. When set, the sitemap isn't used, so the crawl follows the starting page's links. Useful for testing. |
| `use_sitemap` | `true` | `true`, `false` | Also crawl pages listed in the site's sitemap, which can include pages nothing links to. |
| `respect_robots` | `true` | `true`, `false` | Obey the site's `robots.txt`, which says which pages automated tools shouldn't visit. Leave on unless you have permission. |

### What to publish

| Setting | Default | Values | Meaning |
|---|---|---|---|
| `offsite_documents` | `true` | `true`, `false` | Also download documents the site links to on other websites. They go in `documents.zip`, and in the page list under "From other websites". |
| `site_files` | `false` | `true`, `false` | Also publish every captured file (HTML, CSS, scripts, images, fonts, documents) as ordinary files in `site-files.zip`. Roughly doubles the size of each capture; worth it when you may want to reuse or rebuild the site, with the owner's permission. |
| `document_extensions` | common document types | list | File extensions treated as documents. The default: `.pdf .doc .docx .odt .rtf .txt .xls .xlsx .ods .csv .ppt .pptx .odp .zip .epub .xml .json`. Documents are also recognised by type (PDF, Word, Excel...) and by the file name the server sends, so this list mainly matters for unusual formats. Setting it replaces the whole list. |
| `max_offsite_documents` | `2000` | a number | Most documents to download from other websites per capture. Extra ones are listed in the report. |

### When to capture

| Setting | Default | Values | Meaning |
|---|---|---|---|
| `schedule` | `once` | `once`, `weekly`, `monthly`, `off` | `once`: capture when first added, then never automatically. `weekly` / `monthly`: capture again 7 / 30 days after the last capture, at the next daily run. `off`: keep the entry and its captures, but don't capture. You can still capture any site on demand from the **Run workflow** form. |

### How each run works

These rarely need changing. See [runs.md](runs.md) for the background.

| Setting | Default | Values | Meaning |
|---|---|---|---|
| `time_limit_hours` | `5` | up to `5` | How long each part crawls before stopping and handing over to the next part. Can't be more than 5, because GitHub stops a job at 6 hours and the rest of the job needs time to package and upload. |
| `workers` | `4` | `1` to about `8` | Pages loaded at the same time. More is faster but harder on the site and more likely to be blocked; use `1` or `2` for small or fragile sites. |
| `max_parts` | `50` | a number | Stop continuing a capture after this many parts. At 5 hours each, 50 parts is about 10 days of crawling. The dashboard shows the capture as Stopped. |

## `dashboard:`

```yaml
dashboard:
  markdown: true    # DASHBOARD.md in this repository
  web_page: true    # docs/index.html and the page lists, for GitHub Pages
```

| Setting | Default | Meaning |
|---|---|---|
| `markdown` | `true` | Build `DASHBOARD.md`, readable on GitHub. |
| `web_page` | `true` | Build the web dashboard (`docs/index.html`) and a page list for every capture (`docs/captures/`). To put them online, turn on **Settings → Pages → Deploy from a branch → main, /docs** once. |

See [dashboard-and-page-list.md](dashboard-and-page-list.md).

## Examples

A small site, kept in full for possible reuse:

```yaml
sites:
  - url: https://decodendis.pplx.app/
    name: decodendis
    site_files: true
```

A large government site, captured monthly, skipping search and paged listing pages:

```yaml
sites:
  - url: https://www.ndis.gov.au/
    schedule: monthly
    scope: host
    exclude:
      - /search
      - \?page=
```

One section of a site only:

```yaml
sites:
  - url: https://www.example.gov.au/about-us/publications/
    scope: prefix
```

Pause a site without losing it from the dashboard:

```yaml
  - url: https://www.example.gov.au
    schedule: off
```

## Error messages

The **Test** check (and any capture run) stops with one of these if `sites.yaml` has a problem:

| Message | Fix |
|---|---|
| `Each site needs a url` | Every entry under `sites:` must have `url:`. Check the dash and indentation. |
| `Not a web address: ...` | The URL must start with `http://` or `https://`. |
| `...: schedule must be one of [...]` | Use `once`, `weekly`, `monthly` or `off`. |
| `...: scope must be one of [...]` | Use `host`, `domain` or `prefix`. |
| `... and ... have the same name ...` | Two sites make the same short name, e.g. `example.org` and `www.example.org`. Give one of them `name:`. |
| `Unknown defaults: [...]` | A setting under `defaults:` is misspelled. Compare with the tables above. |
| `...: unknown setting(s) [...]; check the spelling` | A setting on that site is misspelled. Compare with the tables above. |
| `Unknown dashboard settings: [...]` | Only `markdown` and `web_page` are allowed under `dashboard:`. |
| `Could not make a name from ...; add name:` | Add `name:` to that site. |
| A YAML error mentioning a line and column | Usually indentation, or a `:` or `#` inside a value; put such values in quotes. |
