# Resource schemas and access boundaries

No full third-party KB, formal evaluation corpus or sealed response cache is bundled. Supply only data you may lawfully use. `examples/synthetic_demo.json` is fictitious and separately licensed as original demonstration material.

- Journal JSON: array of records with `name_cn`, `name_en`, optional `source`, `confidence`, `metadata`. JournalKB does not use `alias_cn` for independent matching.
- Title JSON: array with `record_id`, `title_cn`/`title_cn_clean`, `title_en`/`title_en_clean`, `journal_cn`, `year`, `verification_status="verified"`, `is_official=true`. Additional source/provenance fields may be retained. Do not label unverified real records official to obtain a hit.
- Optional entity JSON: `name_cn`, `name_en`, optional `alias_cn`, `source`, `confidence`; used by EntityKB, not the formal journal-reference hybrid.
- Gold CSV: `Record_ID`, `Chinese_Reference`, `Chinese_Title`, `Chinese_Journal`, `English_Author_Gold_Full` (semicolon-separated), `Year_Gold`, `English_Title_Gold`, `Volume_Issue_Pages_Gold`, `English_Journal_Gold`. `APA_Gold` and original Chinese author fields can be retained for documentation. Despite the historical field name, final author Gold may contain APA initials.
- Prediction CSV: `Record_ID`, `Pred_English_Authors` (JSON array), `Pred_English_Title`, `Pred_English_Journal`, `Pred_Year`, `Pred_Volume`, `Pred_Issue`, `Pred_Pages`.

The local-only 300-record CSV was derived from sealed Stage B, one-to-one by Record_ID, without translating or correcting Gold. Public release of that file remains pending rights review. `docs/frozen_asset_manifest.json` records checksums, not download authorization.

